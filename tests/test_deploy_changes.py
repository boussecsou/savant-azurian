from scripts.should_deploy_agent import requires_agent_deploy


def test_docs_only_does_not_deploy():
    assert not requires_agent_deploy(["docs/notion.md", "README.md", ".github/workflows/ci.yml"])


def test_bff_only_does_not_deploy_agent():
    assert not requires_agent_deploy(
        ["Dockerfile.bff", "src/savant/oauth_callback.py", "scripts/smoke_test_bff.py", "tests/test_bff_smoke.py"]
    )


def test_bff_logging_hardening_and_its_pipeline_gate_do_not_deploy_agent():
    assert not requires_agent_deploy(
        [
            "src/savant/bff_logging.py",
            "src/savant/oauth_callback.py",
            "scripts/should_deploy_agent.py",
            "tests/test_bff_logging.py",
            "tests/test_oauth_runtime.py",
            "tests/test_deploy_changes.py",
            "docs/bff-logging-audit.md",
            "docs/cd-workflow.md",
        ]
    )


def test_bff_changes_do_not_hide_a_shared_or_agent_runtime_change():
    for path in (
        "src/savant/agent.py",
        "src/savant/notion_oauth.py",
        "src/savant/oauth_key.py",
        "src/savant/oauth_runtime.py",
        "pyproject.toml",
    ):
        assert requires_agent_deploy(
            [
                "src/savant/bff_logging.py",
                "scripts/should_deploy_agent.py",
                path,
            ]
        )


def test_agent_or_shared_changes_do_deploy():
    assert requires_agent_deploy(["src/savant/agent.py"])
    assert requires_agent_deploy(["src/savant/oauth_runtime.py", "Dockerfile.bff"])
    assert requires_agent_deploy(["azure.yaml"])
    assert requires_agent_deploy(["uv.lock"])


def test_unknown_or_empty_changes_fail_open():
    assert requires_agent_deploy(["some-new-config.xyz"])
    assert requires_agent_deploy([])
