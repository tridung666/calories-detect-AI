from unittest.mock import Mock
from pydantic import SecretStr

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


def test_liveness_does_not_need_configuration():
    with TestClient(app) as client:
        assert client.get('/health').json() == {'status': 'ok'}


def test_readiness_without_provider_calls(monkeypatch):
    import app.main as main
    settings = Settings(_env_file=None, openai_api_key='', openai_model='')
    monkeypatch.setattr(main, 'get_settings', lambda: settings)
    provider = Mock(side_effect=AssertionError('Health checks must not invoke OpenAI'))
    monkeypatch.setattr('app.services.meal_analysis.get_meal_analysis_service', provider)
    with TestClient(app) as client:
        response = client.get('/ready')
        assert response.status_code == 503
        assert response.json() == {'status': 'not_configured'}
        settings.openai_api_key = SecretStr('test-key')
        settings.openai_model = 'test-model'
        response = client.get('/ready')
        assert response.status_code == 200
        assert response.json() == {'status': 'ready'}
    provider.assert_not_called()
