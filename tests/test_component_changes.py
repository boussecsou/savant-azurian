import json
import subprocess

import pytest

from scripts.component_changes import classify, classify_checks, load_manifest
from scripts.release_plan import changed_since, last_checkpoint, verify_ci


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
        "workflow": "frontend.yml",
    }
    result = classify(["frontend/app.js"], manifest)
    assert result["frontend"]["runtime"]
    assert not result["agent"]["runtime"] and not result["bff"]["runtime"]


def test_component_registry_rejects_bad_workflows_and_ambiguous_paths(tmp_path):
    data = load_manifest()
    data["components"]["bff"]["source_files"].append("src/../secret.py")
    file = tmp_path / "components.json"
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_manifest(file)


def test_full_range_detects_an_earlier_change_and_renamed_shared_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    shared = tmp_path / "src/savant/notion_oauth.py"
    shared.parent.mkdir(parents=True)
    shared.write_text("shared")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    shared.rename(shared.with_name("new_agent_module.py"))
    git("add", "-A")
    git("commit", "-qm", "rename shared source")
    (tmp_path / "README.md").write_text("docs")
    git("add", ".")
    git("commit", "-qm", "docs")
    head = git("rev-parse", "HEAD")
    assert changed_since(base, head, "agent")
    assert changed_since(base, head, "bff")
    assert not changed_since(head, head, "bff")
    assert changed_since("f" * 40, head, "bff")


def test_checkpoint_artifact_pagination_and_legacy_bff_name():
    sha = "a" * 40

    def request(endpoint):
        if "/workflows/" in endpoint:
            return {"workflow_runs": [{"id": 2}, {"id": 1}]}
        if "/runs/2/" in endpoint:
            return {"artifacts": []}
        if endpoint.endswith("page=1"):
            return {"artifacts": [{"name": "other", "expired": False}] * 100}
        return {"artifacts": [{"name": f"bff-checkpoint-{sha}", "expired": False}]}

    assert last_checkpoint("owner/repo", "3", "bff", "publish-bff.yml", request) == sha


def test_ci_must_be_successful_push_for_exact_sha_in_the_same_repo():
    sha = "a" * 40
    run = {
        "head_sha": sha,
        "head_branch": "main",
        "event": "push",
        "conclusion": "success",
        "head_repository": {"full_name": "owner/repo"},
    }
    verify_ci("owner/repo", sha, lambda _: {"workflow_runs": [run]})
    for changed in (
        {"event": "pull_request"},
        {"head_sha": "b" * 40},
        {"conclusion": "failure"},
        {"head_repository": {"full_name": "other/repo"}},
    ):
        with pytest.raises(RuntimeError):
            verify_ci("owner/repo", sha, lambda _, changed=changed: {"workflow_runs": [run | changed]}, attempts=1)


def test_ci_lookup_retries_while_github_api_lags_behind_the_finished_run():
    sha = "a" * 40
    run = {
        "head_sha": sha,
        "head_branch": "main",
        "event": "push",
        "conclusion": "success",
        "head_repository": {"full_name": "owner/repo"},
    }
    answers = iter([[], [], [run]])
    sleeps = []
    verify_ci("owner/repo", sha, lambda _: {"workflow_runs": next(answers)}, attempts=4, delay=2, sleep=sleeps.append)
    assert sleeps == [2, 2]


def test_ci_lookup_gives_up_after_the_last_attempt():
    sleeps = []
    with pytest.raises(RuntimeError):
        verify_ci("owner/repo", "a" * 40, lambda _: {"workflow_runs": []}, attempts=3, delay=1, sleep=sleeps.append)
    assert sleeps == [1, 1]


def test_superseded_head_never_releases_or_advances_checkpoint(monkeypatch):
    from scripts import release_plan

    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr(release_plan.subprocess, "check_output", lambda *a, **kw: "a" * 40)
    monkeypatch.setattr(release_plan, "api", lambda _: {"object": {"sha": "b" * 40}})
    result = release_plan.plan("agent")
    assert result["reason"] == "superseded-main"
    assert result["release"] is False and result["eligible"] is False
