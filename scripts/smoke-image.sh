#!/usr/bin/env bash
set -euo pipefail

image="${1:-calories-detect-ai:test}"
container="calories-ai-smoke-${RANDOM}-${RANDOM}"
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT

# Placeholder credentials satisfy configuration readiness; no provider invocation.
docker run -d --name "$container" \
  -e OPENAI_API_KEY=offline-smoke-key -e OPENAI_MODEL=offline-smoke-model \
  "$image" >/dev/null

for attempt in {1..60}; do
  health="$(docker inspect --format '{{.State.Health.Status}}' "$container")"
  if [[ "$health" == healthy ]]; then
    break
  fi
  if [[ "$health" == unhealthy || "$(docker inspect --format '{{.State.Running}}' "$container")" != true ]]; then
    docker logs "$container"
    exit 1
  fi
  sleep 1
done
[[ "$health" == healthy ]] || { docker logs "$container"; exit 1; }

docker exec -i "$container" python - <<'PY'
import json
import os
import urllib.error
import urllib.request

assert os.getuid() != 0, 'Container must run as a non-root user'
assert not os.path.exists('/app/.env'), 'Image must not contain the host .env'
for path, expected in [('/health', {'status': 'ok'}), ('/ready', {'status': 'ready'})]:
    with urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=3) as response:
        assert json.load(response) == expected
request = urllib.request.Request('http://127.0.0.1:8000/api/v1/meals/analyze',
                                 data=b'{}', headers={'Content-Type': 'application/json'})
try:
    urllib.request.urlopen(request, timeout=3)
except urllib.error.HTTPError as error:
    assert error.code == 422
    assert isinstance(json.load(error)['detail'], list)
else:
    raise AssertionError('Invalid input must be rejected before contacting OpenAI')
print('Docker smoke passed: non-root, no .env, health, readiness, request validation')
PY
