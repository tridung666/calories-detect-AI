# Meal image analysis service

CI verifies Python 3.12 and 3.14; the Docker image uses Python 3.12. This workspace had no existing application or
dependency conventions; the service uses FastAPI, Pydantic, and langchain-openai.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Fill in OPENAI_API_KEY and OPENAI_MODEL in .env.
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Required configuration: `OPENAI_API_KEY` and `OPENAI_MODEL`. Select a model that
supports image inputs and strict JSON Schema structured outputs. Spring sends only `imageUrl`
and attaches the meal ID to the result on its side. There is no
hardcoded model fallback. Optional `OPENAI_TIMEOUT_SECONDS` defaults to 60 and
bounds the entire model invocation; automatic API retries are disabled.
Environment variables override `.env`. The app imports and starts without
credentials, but analysis returns 503 until configured.

```sh
curl --fail-with-body -X POST http://127.0.0.1:8000/api/v1/meals/analyze \
  -H 'Content-Type: application/json' \
  -d '{"imageUrl":"https://res.cloudinary.com/YOUR_CLOUD/image/upload/meal.jpg"}'
```

Success returns only `{"items":[...]}`, with name, estimatedGrams, calories,
protein, carbohydrate, fat, and confidence for each item. Nutrition values are
estimates for the pictured portion. The request accepts only `imageUrl`.
Distinct foods are listed separately. Portion and nutrition values are rounded to two decimal
places, names are limited to 255 characters, portions to 99999999.99 g, and nutrition
values to 2147483647 to match the backend confirmation/storage limits. Confidence
retains its precision. Very small portions that round to zero are rejected.

OpenAI downloads the supplied HTTP(S) image URL; it must be publicly accessible
(including any necessary URL signature). This service does not download images,
access a database, persist predictions, or call the backend. Image failures
reported by OpenAI are translated to 422.

Errors use JSON `{"code":"...","detail":"..."}`; request validation uses FastAPI's standard
JSON validation details:

| Status | Condition |
| --- | --- |
| 422 | Missing or malformed input, inaccessible/invalid image, no food detected |
| 502 | OpenAI failure, incompatible model, refusal, malformed or invalid predictions |
| 503 | Missing configuration, invalid credentials/model permissions, rate limit/quota |
| 504 | OpenAI or end-to-end analysis timeout |

Strict JSON Schema controls the output structure and types. Pydantic validates
all fields, forbids unexpected fields, and rejects blanks, nonfinite numbers,
negative nutrition values, zero/negative portions, and confidence outside 0–1
before any prediction is returned. Provider schemas omit value-bound keywords
for compatibility with OpenAI's JSON Schema subset; local validation retains them.

Machine-readable 422 codes are `no_food_detected` and `invalid_image`; other service
errors currently use `analysis_failed`. Standard request-validation errors retain FastAPI's
`detail` list. Spring distinguishes these instead of parsing human-readable messages.

`GET /health` is process liveness. `GET /ready` checks provider configuration without
making provider calls. Spring connection and frontend integration are documented in the backend repository:
`docs/deployment.md` and `docs/meal-analysis-frontend.md`.

Run `pytest` for offline tests. Tests mock model/HTTP responses and do not spend
OpenAI credits. A real image analysis requires credentials and the curl example.

## Automatic GHCR / VPS deployment

CI runs tests, builds the Docker image, checks its health and validates the local
`compose.yaml`. After CI succeeds for a push to the default branch, CD publishes
`ghcr.io/<owner>/<repository>:sha-<full-commit-sha>` and `:latest`, then deploys the
SHA tag. Pull requests do not publish or deploy. A manual CD run on the default
branch runs Python tests before publishing.

Set these GitHub Actions secrets (repository secrets or the `production`
environment's secrets):

| Secret | Value |
| --- | --- |
| `VPS_HOST` | VPS hostname or IP address |
| `VPS_PORT` | SSH port; defaults to `22` |
| `VPS_USER` | SSH user with Docker access and write access to the deployment directory |
| `VPS_SSH_KEY` | Private SSH key authorized for that user |

Set the optional Actions variable `VPS_DEPLOY_PATH` to the directory containing
the existing `docker-compose.yml` and `.env`; it defaults to
`/opt/calories-detect`. An optional `VPS_SSH_KNOWN_HOSTS` secret can pin the VPS
host key. Otherwise CD discovers the host key with `ssh-keyscan`.
SSH connection secrets belong in GitHub Actions, not in the VPS application's
`.env`. Publishing uses GitHub's automatic `GITHUB_TOKEN` with `packages: write`.

On the VPS, add `ai` to the existing `services` in `docker-compose.yml` once.
Keep the existing frontend, backend and PostgreSQL configuration. The image
name must match this repository's GHCR package (lowercase owner/repository):

```yaml
services:
  # Existing fe, be and PostgreSQL services remain here.
  ai:
    image: ghcr.io/tridung666/calories-detect-ai:${AI_TAG:?Set AI_TAG}
    environment:
      OPENAI_API_KEY: ${OPENAI_API_KEY:?Set OPENAI_API_KEY}
      OPENAI_MODEL: ${OPENAI_MODEL:?Set OPENAI_MODEL}
      OPENAI_TIMEOUT_SECONDS: ${OPENAI_TIMEOUT_SECONDS:-60}
    restart: unless-stopped
    expose:
      - "8000"
    init: true
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
```

This example uses the default Compose network. If the backend uses a custom
network, attach `ai` to that same network so the backend can call
`http://ai:8000`. The Docker image includes a `/ready` healthcheck; it checks
configuration without spending provider credits.

Keep the existing `.env` entries and add `AI_TAG=latest` for the initial
deployment, plus `OPENAI_API_KEY` and `OPENAI_MODEL`. CD subsequently replaces
`AI_TAG` with the release's SHA tag. No overlay, `.env.ai`, uploaded deployment
script or source checkout is needed on the VPS.

The VPS needs Docker Compose v2 with `--wait`, Bash, `flock`, and GNU `sed`.
Install the Compose plugin in a system plugin directory so it is available
with a temporary Docker configuration directory. CD logs the VPS in to GHCR
using its short-lived `GITHUB_TOKEN` with `packages: read`. Credentials travel
over SSH stdin and are stored in a temporary Docker configuration that is
deleted when deployment finishes. No separate GHCR PAT or persistent VPS login
is required for the package published by this repository. If package access has
been customized, grant this repository Actions access to its GHCR package.

CD locks `.deploy.lock`, remembers the previous `AI_TAG`, updates that tag,
and runs:

```sh
docker compose --env-file .env -f docker-compose.yml pull ai
docker compose --env-file .env -f docker-compose.yml up -d --no-deps --no-build --wait --wait-timeout 120 ai
```

Only `ai` is updated. Other deployment pipelines should use the same lock when
modifying this Compose project or `.env`. If validation, pulling or startup
fails, CD restores only the previous `AI_TAG` and attempts to restart that AI
release, preserving other services' tags and environment changes. It then marks
the deployment failed. A rollback failure is also reported in the
workflow logs. The first deployment has no previous running release to restore.

References: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[OpenAI vision](https://developers.openai.com/api/docs/guides/images-vision),
[LangChain structured output](https://reference.langchain.com/python/langchain-openai/chat_models/base/ChatOpenAI/with_structured_output),
[GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
[Docker Compose startup and health checks](https://docs.docker.com/reference/cli/docker/compose/up/).
