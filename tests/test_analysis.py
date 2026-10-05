import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from openai import (
    APIConnectionError, APITimeoutError, AuthenticationError, BadRequestError,
    InternalServerError, PermissionDeniedError, RateLimitError,
)

from app.api import meals
from app.core.config import Settings
from app.main import app
from app.services import meal_analysis
from app.services.meal_analysis import MealAnalysisService, prediction_json_schema


REQUEST = {"imageUrl": "https://example.com/meal.jpg"}
PATH = "/api/v1/meals/analyze"


@pytest.fixture
def model(monkeypatch):
    runnable = AsyncMock()
    service = MealAnalysisService(runnable, timeout_seconds=1)
    monkeypatch.setattr(meals, "get_meal_analysis_service", lambda: service)
    return runnable


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def result(parsed, parsing_error=None):
    return {
        "parsed": parsed, "parsing_error": parsing_error,
        "raw": AIMessage(content=json.dumps(parsed)),
    }


def test_valid_structured_result(client, model, nutrition_item):
    model.ainvoke.return_value = result({"items": [nutrition_item]})
    response = client.post(PATH, json=REQUEST)
    assert response.status_code == 200
    assert response.json() == {"items": [nutrition_item]}
    assert response.headers["content-type"] == "application/json"
    messages = model.ainvoke.call_args.args[0]
    assert messages[1].content[1] == {"type": "image_url", "image_url": {"url": REQUEST["imageUrl"]}}


@pytest.mark.parametrize("output", [
    result(None), result({"items": []}, ValueError("bad JSON")),
    result({"items": "not-a-list"}), result({"items": [{"name": "Rice"}]}),
    result({"items": [], "explanation": "extra"}), "```json\n{}\n```",
])
def test_invalid_structured_output(client, model, output):
    model.ainvoke.return_value = output
    response = client.post(PATH, json=REQUEST)
    assert response.status_code == 502
    assert "invalid structured" in response.json()["detail"]


def test_invalid_nutrition_result(client, model, nutrition_item):
    model.ainvoke.return_value = result({"items": [{**nutrition_item, "estimatedGrams": 0}]})
    assert client.post(PATH, json=REQUEST).status_code == 502


def test_empty_detection(client, model):
    model.ainvoke.return_value = result({"items": []})
    response = client.post(PATH, json=REQUEST)
    assert response.status_code == 422
    assert response.json() == {"code": "no_food_detected", "detail": "No food detected in the image."}


@pytest.mark.parametrize("payload", [
    {}, {"imageUrl": "bad-url"},
    {"imageUrl": ""},
])
def test_request_validation_without_configuration(client, monkeypatch, payload):
    factory = AsyncMock()
    monkeypatch.setattr(meals, "get_meal_analysis_service", factory)
    assert client.post(PATH, json=payload).status_code == 422
    factory.assert_not_called()


def provider_error(error_type, status, code=None, param=None):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return error_type("sensitive upstream message", response=response, body={"code": code, "param": param})


@pytest.mark.parametrize("error,status,detail", [
    (provider_error(BadRequestError, 400, "invalid_image_url"), 422, "image could not be accessed"),
    (provider_error(BadRequestError, 400, "image_download_failed"), 422, "image could not be accessed"),
    (provider_error(BadRequestError, 400, "invalid_value", "messages[1].content[1].image_url"), 422, "image could not be accessed"),
    (provider_error(BadRequestError, 400, "invalid_model"), 502, "model compatibility"),
    (provider_error(AuthenticationError, 401), 503, "credentials"),
    (provider_error(PermissionDeniedError, 403), 503, "model access"),
    (provider_error(RateLimitError, 429), 503, "rate limited"),
    (provider_error(InternalServerError, 500), 502, "analysis failed"),
    (APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")), 502, "analysis failed"),
    (APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")), 504, "timed out"),
    (OutputParserException("bad JSON"), 502, "invalid structured"),
])
def test_provider_failure(client, model, error, status, detail):
    model.ainvoke.side_effect = error
    response = client.post(PATH, json=REQUEST)
    assert response.status_code == status
    assert detail in response.json()["detail"]
    assert "sensitive" not in response.text


def test_invocation_deadline(client, monkeypatch):
    async def delayed_response(messages):
        await asyncio.sleep(1)

    runnable = AsyncMock()
    runnable.ainvoke.side_effect = delayed_response
    monkeypatch.setattr(meals, "get_meal_analysis_service", lambda: MealAnalysisService(runnable, 0.01))
    assert client.post(PATH, json=REQUEST).status_code == 504


@pytest.mark.parametrize("key,model", [("", "vision-model"), ("test-key", ""), ("  ", "  ")])
def test_missing_configuration(client, monkeypatch, key, model):
    monkeypatch.setattr(meal_analysis, "get_settings", lambda: Settings(
        _env_file=None, openai_api_key=key, openai_model=model
    ))
    meal_analysis.get_meal_analysis_service.cache_clear()
    try:
        response = client.post(PATH, json=REQUEST)
        assert response.status_code == 503
        assert "OPENAI_API_KEY and OPENAI_MODEL" in response.json()["detail"]
    finally:
        meal_analysis.get_meal_analysis_service.cache_clear()


def test_configuration_env_conventions(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=file-key\nOPENAI_MODEL=file-model\nOPENAI_TIMEOUT_SECONDS=15\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    settings = Settings(_env_file=env_file)
    assert settings.openai_api_key.get_secret_value() == "file-key"
    assert settings.openai_model == "environment-model"
    assert settings.openai_timeout_seconds == 15


def test_factory_uses_config_and_strict_schema(monkeypatch):
    settings = Settings(_env_file=None, openai_api_key="test-key", openai_model="configured-vision-model")
    monkeypatch.setattr(meal_analysis, "get_settings", lambda: settings)
    from unittest.mock import Mock
    model_class = Mock()
    monkeypatch.setattr(meal_analysis, "ChatOpenAI", model_class)
    meal_analysis.get_meal_analysis_service.cache_clear()
    try:
        meal_analysis.get_meal_analysis_service()
        kwargs = model_class.call_args.kwargs
        assert kwargs["model"] == "configured-vision-model"
        assert kwargs["api_key"] == settings.openai_api_key
        assert kwargs["max_retries"] == 0
        assert kwargs["timeout"] == 60
        call = model_class.return_value.with_structured_output.call_args
        assert call.kwargs == {"method": "json_schema", "strict": True, "include_raw": True}
        schema = call.args[0]
        assert schema["additionalProperties"] is False
        item = schema["$defs"]["NutritionItem"]
        assert item["additionalProperties"] is False
        assert set(item["required"]) == set(item["properties"])
        assert "exclusiveMinimum" not in item["properties"]["estimatedGrams"]
    finally:
        meal_analysis.get_meal_analysis_service.cache_clear()


@pytest.mark.parametrize("mode,expected_status", [
    ("valid", 200), ("markdown", 502), ("truncated", 502),
    ("length", 502), ("content-filter", 502), ("refusal", 502),
    ("invalid-nutrition", 502), ("empty", 422),
])
def test_real_langchain_pipeline_with_mock_openai(nutrition_item, mode, expected_status):
    """Verify actual LangChain serialization, strict contract and JSON parsing offline."""
    requests = []
    content = json.dumps({"items": [nutrition_item]})
    if mode == "markdown":
        content = "```json\n" + content + "\n```"
    elif mode == "truncated":
        content = content[:-1]
    elif mode == "invalid-nutrition":
        content = json.dumps({"items": [{**nutrition_item, "fat": -1}]})
    elif mode == "empty":
        content = '{"items": []}'

    def handle_request(request):
        requests.append(json.loads(request.content))
        finish_reason = {"length": "length", "content-filter": "content_filter"}.get(mode, "stop")
        return httpx.Response(200, json={
            "id": "chatcmpl-test", "object": "chat.completion", "created": 0,
            "model": "configured-vision-model",
            "choices": [{"index": 0, "finish_reason": finish_reason, "message": {
                "role": "assistant", "content": None if mode == "refusal" else content,
                "refusal": "Cannot analyze this image." if mode == "refusal" else None,
            }}],
        })

    async def invoke():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            model = ChatOpenAI(
                api_key="offline-test-key", model="configured-vision-model",
                max_retries=0, http_async_client=http_client,
            ).with_structured_output(prediction_json_schema(), method="json_schema", strict=True, include_raw=True)
            return await MealAnalysisService(model, 5).analyze(REQUEST["imageUrl"])

    if expected_status == 200:
        assert asyncio.run(invoke()).model_dump() == {"items": [nutrition_item]}
    else:
        from app.core.errors import MealAnalysisError
        with pytest.raises(MealAnalysisError) as exc:
            asyncio.run(invoke())
        assert exc.value.status_code == expected_status
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert requests[0]["response_format"]["json_schema"]["strict"] is True
    assert requests[0]["messages"][1]["content"][1]["image_url"]["url"] == REQUEST["imageUrl"]
