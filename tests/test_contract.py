"""Wire fixtures are also consumed by Spring's AiWireContractTest."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from openai import APITimeoutError, BadRequestError

from app.api import meals
from app.core.errors import MealAnalysisError
from app.main import app
from app.services.meal_analysis import MealAnalysisService

CONTRACT = json.loads((Path(__file__).parent / 'fixtures/meal-analysis-contract.json').read_text())


@pytest.mark.parametrize('case', CONTRACT['cases'], ids=lambda case: case['name'])
def test_actual_fastapi_response_matches_spring_wire_contract(monkeypatch, case):
    runnable = AsyncMock()
    parsed = {'items': [CONTRACT['providerItem']]}
    if case['name'] == 'no-food':
        parsed = {'items': []}
    if case['name'] == 'provider-output':
        parsed = {'items': [{'name': 'Incomplete prediction'}]}
    runnable.ainvoke.return_value = {'parsed': parsed, 'parsing_error': None,
                                    'raw': AIMessage(content=json.dumps(parsed))}
    request = httpx.Request('POST', 'https://api.openai.com/v1/chat/completions')
    if case['name'] == 'timeout':
        runnable.ainvoke.side_effect = APITimeoutError(request=request)
    elif case['name'] == 'invalid-image':
        runnable.ainvoke.side_effect = BadRequestError(
            'private provider data', response=httpx.Response(400, request=request),
            body={'code': 'invalid_image_url'})
    elif case['name'] == 'unavailable':
        def unavailable():
            raise MealAnalysisError(503, case['body']['detail'])
        monkeypatch.setattr(meals, 'get_meal_analysis_service', unavailable)
    if case['name'] != 'unavailable':
        monkeypatch.setattr(meals, 'get_meal_analysis_service', lambda: MealAnalysisService(runnable, 1))
    with TestClient(app) as client:
        response = client.post('/api/v1/meals/analyze', json=CONTRACT['request'])
    assert response.status_code == case['status']
    assert response.json() == case['body']
    assert 'private provider data' not in response.text
