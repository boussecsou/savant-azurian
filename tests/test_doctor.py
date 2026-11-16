"""The prerequisites check: version parsing and the required/optional distinction."""

from scripts import doctor
from scripts.doctor import Tool


def test_versions_are_read_from_typical_outputs():
    assert doctor.parse_version("v22.12.0") == (22, 12, 0)
    assert doctor.parse_version("uv 0.12.0 (abc 2026-01-01)") == (0, 12, 0)
    assert doctor.parse_version("azd version 1.37.3 (commit c79)") == (1, 37, 3)
    assert doctor.parse_version("no digits") is None


def test_a_missing_tool_is_reported_not_raised():
    assert doctor.check_tool(Tool("x", ["x"], "nothing", "n/a"), lambda command: None) == (False, "not found")


def test_a_too_old_tool_fails_its_minimum():
    node = Tool("node", ["node", "--version"], "web", "n/a", True, (22,))
    assert doctor.check_tool(node, lambda command: "v20.1.0")[0] is False
    assert doctor.check_tool(node, lambda command: "v22.12.0")[0] is True


def test_only_a_missing_required_tool_fails_the_report():
    def runner(command):
        return None if command[0] in {"docker", "az", "azd", "gh", "just"} else "v22.12.0"

    lines, failed = doctor.report(runner)
    assert failed is False
    assert any(line.startswith("--") and "docker" in line for line in lines)

    lines, failed = doctor.report(lambda command: None)
    assert failed is True


def test_the_python_requirement():
    assert doctor.check_python((3, 13, 1))[0] is True
    assert doctor.check_python((3, 12, 9))[0] is False
