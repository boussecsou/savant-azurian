"""Keep every configuration surface in step with docs/configuration.md.

Surfaces checked: the code (environment reads), `.env.example`, `azure.yaml`, the Bicep outputs and
parameters (when `infra/` exists), and the GitHub workflows. Adding a variable to any of them without describing it in
`docs/configuration.md` fails this test, so a new contributor never meets an undocumented setting.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NAME = r"[A-Z][A-Z0-9_]{2,}"

# Scopes whose variables the code must really read, and that `.env.example` must list.
CODE_SCOPES = {"agent", "bff", "local", "script"}
# Scopes the code never reads: platform, CI, azd/Bicep and Azure SDK variables.
OTHER_SCOPES = {"platform", "ci", "azd", "sdk"}

ENV_READERS = {"get", "getenv", "_env_names", "_env_bool"}


def documented() -> dict[str, str]:
    """Variable name -> scope, from the tables of docs/configuration.md."""
    found: dict[str, str] = {}
    for line in (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8").splitlines():
        match = re.match(rf"^\| `({NAME})` \| (\w+) \|", line)
        if match:
            assert match[1] not in found, f"{match[1]} is documented twice"
            found[match[1]] = match[2]
    return found


def _first_string(node: ast.Call) -> str | None:
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def read_by_code() -> dict[str, set[str]]:
    """Environment variables read by src/ and scripts/, with the files that read them."""
    found: dict[str, set[str]] = {}
    files = [*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").glob("*.py"), ROOT / "main.py"]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                called = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
                if called in ENV_READERS and (value := _first_string(node)) and re.fullmatch(NAME, value):
                    # `.get("X")` is only an environment read when the receiver looks like the
                    # environment; dict lookups such as `values.get("X")` are not.
                    receiver = ast.unparse(function.value) if isinstance(function, ast.Attribute) else ""
                    if called != "get" or receiver in {"os.environ", "env"}:
                        names.add(value)
            elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    names.add(node.slice.value)
            elif isinstance(node, ast.Assign):
                # Tuples of required names, such as _SSH_REQUIRED = ("SSH_HOST", ...).
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if any(t.endswith("_REQUIRED") for t in targets) and isinstance(node.value, (ast.Tuple, ast.List)):
                    names.update(e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
        if path.name == "search_setup.py":
            # The pipeline script validates a dict keyed by variable names.
            names.update(
                node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(r"SEARCH_[A-Z_]+", node.value)
            )
        for name in names:
            found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return found


def env_example_names() -> set[str]:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return set(re.findall(rf"^#?\s*({NAME})=", text, re.MULTILINE))


def test_documentation_has_valid_scopes():
    unknown = {n: s for n, s in documented().items() if s not in CODE_SCOPES | OTHER_SCOPES}
    assert not unknown, f"Unknown scope in docs/configuration.md: {unknown}"


def test_every_variable_the_code_reads_is_documented():
    missing = sorted(set(read_by_code()) - set(documented()))
    assert not missing, f"Read by the code but missing from docs/configuration.md: {missing}"


def test_documented_code_variables_are_really_read():
    reads = set(read_by_code())
    stale = sorted(n for n, scope in documented().items() if scope in CODE_SCOPES and n not in reads)
    assert not stale, f"Documented with a code scope but no longer read by the code: {stale}"


def test_env_example_only_lists_documented_variables():
    unknown = sorted(env_example_names() - set(documented()))
    assert not unknown, f".env.example has undocumented variables: {unknown}"


def test_env_example_lists_every_local_variable():
    missing = sorted(n for n, scope in documented().items() if scope in CODE_SCOPES and n not in env_example_names())
    assert not missing, f"Documented but missing from .env.example: {missing}"


def test_azure_yaml_reads_only_documented_variables():
    text = (ROOT / "azure.yaml").read_text(encoding="utf-8")
    used = set(re.findall(rf"\$\{{({NAME})\}}", text))
    assert used, "azure.yaml should be parameterized with ${VAR}"
    assert not sorted(used - set(documented())), f"azure.yaml uses undocumented variables: {sorted(used - set(documented()))}"


def test_azure_yaml_keeps_no_personal_values():
    text = (ROOT / "azure.yaml").read_text(encoding="utf-8")
    guid = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)
    hosts = re.findall(r"https://[a-z0-9.-]+\.(?:azure\.com|azurecontainerapps\.io|windows\.net|azure\.net)", text)
    ip = re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text)
    assert not guid and not hosts and not ip, "azure.yaml must only reference ${VAR}, not literal Azure values"


def test_bicep_outputs_and_inputs_are_documented():
    if not (ROOT / "infra" / "main.bicep").exists():
        pytest.skip("no infra/ folder yet")
    main = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
    params = (ROOT / "infra" / "main.bicepparam").read_text(encoding="utf-8")
    outputs = set(re.findall(rf"^output ({NAME}) ", main, re.MULTILINE))
    inputs = set(re.findall(rf"readEnvironmentVariable\('({NAME})'", params))
    assert outputs and inputs
    missing = sorted((outputs | inputs) - set(documented()))
    assert not missing, f"Bicep uses variables missing from docs/configuration.md: {missing}"


def test_workflow_variables_are_documented():
    used: set[str] = set()
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        used.update(re.findall(rf"vars\.({NAME})", workflow.read_text(encoding="utf-8")))
    missing = sorted(used - set(documented()))
    assert not missing, f"Workflows read GitHub variables missing from docs/configuration.md: {missing}"


def test_azure_yaml_variables_reach_the_deployment_workflow():
    """CD must set, in the azd environment, every variable azure.yaml reads (except azd's own)."""
    azure = set(re.findall(rf"\$\{{({NAME})\}}", (ROOT / "azure.yaml").read_text(encoding="utf-8")))
    cd = (ROOT / ".github" / "workflows" / "cd.yml").read_text(encoding="utf-8")
    missing = sorted(n for n in azure if n not in cd)
    assert not missing, f"cd.yml never sets these azure.yaml variables: {missing}"


@pytest.mark.parametrize("script", sorted((ROOT / "scripts" / "setup").glob("*.sh")))
def test_setup_scripts_are_dry_run_by_default(script):
    text = script.read_text(encoding="utf-8")
    if script.name == "_lib.sh":
        assert "APPLY=0" in text
    else:
        assert "parse_common_flags" in text and "finish" in text, f"{script.name} must support --apply and default to a dry run"
