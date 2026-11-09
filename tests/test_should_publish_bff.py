import subprocess

import pytest

from bff.should_publish import changed_since, last_checkpoint, requires_publication


@pytest.mark.parametrize("path", [
    "Dockerfile.bff", "Dockerfile.bff.dockerignore", ".dockerignore",
    "pyproject.toml", "uv.lock", "src/savant/oauth_callback.py",
    "src/savant/notion_oauth.py", "src/savant/oauth_runtime.py",
    "scripts/package_bff.py", ".github/components.json",
])
def test_shipped_inputs_trigger_publication(path):
    assert requires_publication([path])


def test_docs_tests_and_agent_manifest_do_not_trigger_publication():
    assert not requires_publication(["docs/perso.md", "tests/test_graph.py", "azure.yaml"])
    assert not requires_publication(["src/savant/tools/notion.py", "src/savant/agent.py"])
    assert not requires_publication(["bff/publish.sh", ".github/workflows/publish-bff.yml"])
    assert not requires_publication([])


def test_checkpoint_ignores_current_run_and_expired_artifacts():
    sha = "a" * 40
    def request(endpoint):
        if "/workflows/" in endpoint:
            return {"workflow_runs": [{"id": 3}, {"id": 2}, {"id": 1}]}
        run_id = int(endpoint.split("/runs/")[1].split("/")[0])
        return {"artifacts": [{"name": f"bff-checkpoint-{sha}", "expired": run_id == 2}]}
    assert last_checkpoint("owner/repo", "3", request) == sha


def test_checkpoint_paginates_runs_without_artifacts():
    def request(endpoint):
        if "/workflows/" in endpoint:
            return {"workflow_runs": [{"id": n} for n in range(100)] if endpoint.endswith("&page=1") else []}
        return {"artifacts": []}
    assert last_checkpoint("owner/repo", "999", request) is None


def test_missing_checkpoint_requires_publication():
    assert changed_since(None, "a" * 40)


def test_full_range_includes_earlier_commits_and_deleted_inputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()
    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (tmp_path / "uv.lock").write_text("old")
    git("add", ".")
    git("commit", "-qm", "baseline")
    base = git("rev-parse", "HEAD")
    (tmp_path / "uv.lock").unlink()
    git("add", "-A")
    git("commit", "-qm", "remove input")
    (tmp_path / "README.md").write_text("docs")
    git("add", ".")
    git("commit", "-qm", "docs")
    assert changed_since(base, git("rev-parse", "HEAD"))
    assert not changed_since(git("rev-parse", "HEAD"), git("rev-parse", "HEAD"))


def test_publication_files_do_not_trigger_foundry_deployment():
    from scripts.should_deploy_agent import requires_agent_deploy

    assert not requires_agent_deploy([
        ".github/workflows/publish-bff.yml", "bff/should_publish.py", "bff/publish.sh",
        "tests/test_should_publish_bff.py", "tests/test_publish_bff.py",
        "docs/publish-bff-workflow.md",
    ])
