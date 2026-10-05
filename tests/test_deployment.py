"""Exercise the exact VPS script with a fake Docker CLI and isolated env files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="The documented VPS uses Linux flock and GNU sed"
)
NEW_TAG = "sha-" + "a" * 40
OLD_TAG = "sha-" + "b" * 40


@pytest.fixture
def deployment(tmp_path):
    stack = tmp_path / "stack with spaces"
    stack.mkdir()
    (stack / "docker-compose.yml").write_text("services: {}\n")
    (stack / ".env").write_text(
        f"AI_TAG={OLD_TAG}\nFRONTEND_TAG=frontend-old\n"
        "BACKEND_TAG=backend-old\nOPENAI_API_KEY=not-a-real-key\n"
    )
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/cd.yml").read_text()
    remote = workflow.split("cat <<'REMOTE'\n", 1)[1].split("\n          REMOTE", 1)[0]
    script = tmp_path / "deploy.sh"
    script.write_text(textwrap.dedent(remote))
    binary = tmp_path / "bin"
    binary.mkdir()
    fake = binary / "docker"
    fake.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''
        import json
        import os
        from pathlib import Path
        import sys

        args = sys.argv[1:]
        env = Path('.env')
        fields = dict(line.split('=', 1) for line in env.read_text().splitlines() if '=' in line)
        with Path(os.environ['DEPLOY_TEST_LOG']).open('a') as stream:
            stream.write(json.dumps({'args': args, 'tag': fields.get('AI_TAG')}) + '\\n')
        if args[0] == 'login':
            sys.stdin.read()
            sys.exit(0)
        assert args[0] == 'compose'
        if '--services' in args:
            print('ai')
            sys.exit(0)
        stage = ('config' if 'config' in args else 'pull' if 'pull' in args else 'up')
        failure = os.environ.get('DEPLOY_TEST_FAILURE')
        new_release = fields.get('AI_TAG') == os.environ['DEPLOY_TEST_NEW_TAG']
        # Simulate a pipeline that has not adopted the shared lock yet.
        if new_release and failure in (stage, 'rollback'):
            env.write_text(env.read_text().replace('FRONTEND_TAG=frontend-old',
                                                   'FRONTEND_TAG=frontend-new'))
            sys.exit(1)
        if failure == 'rollback' and stage == 'up':
            sys.exit(1)
    '''))
    fake.chmod(0o755)
    return stack, script, binary, tmp_path / "docker-calls.jsonl"


def run_deploy(deployment, failure=""):
    stack, script, binary, log = deployment
    variables = dict(os.environ,
                     PATH=str(binary) + os.pathsep + os.environ["PATH"],
                     GHCR_TOKEN="test-registry-token", GHCR_USER="test-user",
                     DEPLOY_TEST_LOG=str(log), DEPLOY_TEST_NEW_TAG=NEW_TAG,
                     DEPLOY_TEST_FAILURE=failure)
    result = subprocess.run(["bash", str(script), NEW_TAG, str(stack)],
                            env=variables, text=True, capture_output=True, timeout=10)
    fields = dict(line.split("=", 1) for line in (stack / ".env").read_text().splitlines()
                  if "=" in line)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result, fields, calls


def assert_other_fields_preserved(fields, frontend):
    assert fields["FRONTEND_TAG"] == frontend
    assert fields["BACKEND_TAG"] == "backend-old"
    assert fields["OPENAI_API_KEY"] == "not-a-real-key"


def test_success_updates_only_ai_tag(deployment):
    result, fields, calls = run_deploy(deployment)
    assert result.returncode == 0, result.stderr
    assert fields["AI_TAG"] == NEW_TAG
    assert_other_fields_preserved(fields, "frontend-old")
    assert [call["tag"] for call in calls if "up" in call["args"]] == [NEW_TAG]


@pytest.mark.parametrize("failure", ["config", "pull", "up"])
def test_failed_deploy_restores_ai_tag_without_overwriting_other_updates(deployment, failure):
    result, fields, calls = run_deploy(deployment, failure)
    assert result.returncode != 0
    assert fields["AI_TAG"] == OLD_TAG
    assert_other_fields_preserved(fields, "frontend-new")
    assert "restoring previous AI_TAG" in result.stderr
    assert [call for call in calls if "up" in call["args"]][-1]["tag"] == OLD_TAG


def test_first_deploy_failure_removes_new_tag_and_reports_no_previous_release(deployment):
    stack, _, _, _ = deployment
    env = stack / ".env"
    env.write_text(env.read_text().replace(f"AI_TAG={OLD_TAG}\n", ""))
    result, fields, calls = run_deploy(deployment, "pull")
    assert result.returncode != 0
    assert "AI_TAG" not in fields
    assert_other_fields_preserved(fields, "frontend-new")
    assert "No previous AI_TAG exists" in result.stderr
    assert not any("up" in call["args"] for call in calls)


def test_rollback_failure_still_restores_tag_and_reports_failure(deployment):
    result, fields, _ = run_deploy(deployment, "rollback")
    assert result.returncode != 0
    assert fields["AI_TAG"] == OLD_TAG
    assert_other_fields_preserved(fields, "frontend-new")
    assert "Previous AI deployment could not be restored" in result.stderr
