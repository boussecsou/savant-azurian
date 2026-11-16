import json

import pytest

from scripts.component_changes import classify, classify_checks, load_manifest


@pytest.mark.parametrize(
    "paths,agent,bff",
    [
        (["src/savant/agent.py"], True, False),
        (["src/savant/tools/notion.py"], True, False),
        (["src/savant/oauth_callback.py"], False, True),
        (["src/savant/bff_logging.py"], False, True),
        (["src/savant/notion_oauth.py"], True, True),
        (["src/savant/oauth_runtime.py"], True, True),
        (["src/savant/oauth_key.py"], True, True),
        (["uv.lock"], True, True),
        (["docs/architecture.md"], False, False),
        (["tests/test_graph.py"], False, False),
        (["pwa/src/api.ts", "pwa/package-lock.json"], False, False),
        (["unknown/new-runtime.toml"], True, True),
        (["src/savant/agent.py", "src/savant/oauth_callback.py"], True, True),
        ([], False, False),
    ],
)
def test_component_runtime_ownership(paths, agent, bff):
    result = classify(paths)
    assert result["agent"]["runtime"] is agent
    assert result["bff"]["runtime"] is bff


def test_bff_ci_runs_for_its_build_and_implementation_but_not_agent_only():
    assert classify(["Dockerfile.bff"])["bff"]["ci"]
    assert classify(["tests/test_bff_smoke.py"])["bff"]["ci"]
    assert not classify(["src/savant/graph.py"])["bff"]["ci"]


def test_pwa_check_runs_for_pwa_and_ci_changes_only():
    assert classify_checks(["pwa/src/App.tsx"]) == {"pwa": True}
    assert classify_checks([".github/workflows/ci.yml"]) == {"pwa": True}
    assert classify_checks(["src/savant/bff_api.py", "docs/x.md"]) == {"pwa": False}


def test_ci_only_checks_cannot_shadow_a_component_or_escape_the_repository(tmp_path):
    for checks in ({"bff": ["pwa/**"]}, {"pwa": ["../outside/**"]}, {"pwa": "pwa/**"}):
        data = load_manifest() | {"checks": checks}
        file = tmp_path / "components.json"
        file.write_text(json.dumps(data))
        with pytest.raises(ValueError):
            load_manifest(file)


def test_new_component_uses_the_same_policy_without_code_changes():
    manifest = load_manifest()
    manifest["components"]["frontend"] = {
        "runtime": ["frontend/**"],
        "source_files": [],
        "exclude": [],
        "ci": ["tests/frontend/**"],
    }
    result = classify(["frontend/app.js"], manifest)
    assert result["frontend"]["runtime"]
    assert not result["agent"]["runtime"] and not result["bff"]["runtime"]


def test_component_registry_rejects_ambiguous_paths(tmp_path):
    data = load_manifest()
    data["components"]["bff"]["source_files"].append("src/../secret.py")
    file = tmp_path / "components.json"
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_manifest(file)
