# Calories Detect AI

FastAPI service that estimates food portions and nutrition from a meal photo using
OpenAI structured outputs. Spring owns authentication, meal ownership and saving
confirmed results; this service returns predictions without storing them.

See [service setup and production deployment](docs/ai-service.md) for the API
contract, environment variables and GHCR/VPS configuration.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Configure OPENAI_API_KEY and OPENAI_MODEL before analyzing an image.
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run `python -m pytest` for tests with the provider mocked, or
`docker compose up -d --build --wait` to run the local container.
