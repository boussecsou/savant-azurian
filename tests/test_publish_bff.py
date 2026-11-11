"""Exercise the publishing shell without Azure, Docker or credentials."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bff/publish.sh"
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
REGISTRY = "registry.azurecr.io"


@pytest.mark.parametrize(
    "scenario,v1,pushes,success",
    [
        ("new", True, 2, True),
        ("existing", False, 0, True),
        ("existing", True, 1, True),
        ("same_v1", True, 0, True),
        ("conflict", True, 0, False),
        ("auth_error", False, 0, False),
        ("bad_revision", False, 0, False),
        ("bad_digest", False, 0, False),
        ("bad_lock", False, 0, False),
    ],
)
def test_publication_contract(tmp_path, scenario, v1, pushes, success):
    fake = tmp_path / "fake"
    fake.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as f:
    f.write(json.dumps([Path(sys.argv[0]).name, *args]) + '\\n')
s = os.environ['SCENARIO']
digest = 'sha256:' + 'b' * 64
sha = 'a' * 40
if Path(sys.argv[0]).name == 'docker':
    if args[0:2] == ['image', 'inspect']:
        if 'RepoDigests' in args[-1]:
            print(json.dumps(['registry.azurecr.io/sa2-bff@' + digest]))
        else:
            print('wrong' if s == 'bad_revision' else sha)
    sys.exit(0)
if args[0:2] == ['acr', 'show']:
    print('registry.azurecr.io')
elif args[0:3] == ['acr', 'repository', 'show-tags']:
    if s in ('new', 'auth_error'):
        print('repository "sa2-bff" is not found' if s == 'new' else 'unauthorized', file=sys.stderr)
        sys.exit(1)
    tags = [{'name': 'sha-' + sha, 'digest': digest}]
    if s == 'same_v1':
        tags.append({'name': 'v1', 'digest': digest})
    if s == 'conflict':
        tags.append({'name': 'v1', 'digest': 'sha256:' + 'c' * 64})
    print(json.dumps(tags))
elif args[0:3] == ['acr', 'repository', 'show']:
    if '--query' in args:
        print('wrong' if s == 'bad_digest' else digest)
    else:
        print(json.dumps({'digest': digest, 'changeableAttributes': {
            'writeEnabled': s == 'bad_lock', 'deleteEnabled': False}}))
""")
    fake.chmod(0o755)
    for tool in ["az", "docker"]:
        (tmp_path / tool).symlink_to(fake)
    env = dict(
        os.environ,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
        ACR_NAME="acrsavantazurian2",
        IMAGE_REPOSITORY="sa2-bff",
        SOURCE_SHA=SHA,
        PUBLISH_V1=str(v1).lower(),
        SCENARIO=scenario,
        CALLS=str(tmp_path / "calls"),
        GITHUB_OUTPUT=str(tmp_path / "output"),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
    )
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    assert sum(call[:2] == ["docker", "push"] for call in calls) == pushes
    if success:
        assert (tmp_path / "output").read_text() == f"digest={DIGEST}\n"
        assert any(call[:4] == ["az", "acr", "repository", "update"] for call in calls)
    else:
        assert not (tmp_path / "output").exists()
