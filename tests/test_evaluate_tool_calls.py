"""Offline tests for the tool-call evaluation: no model call, no credential."""
import json
from types import SimpleNamespace

import pytest

from scripts.evaluate_tool_calls import (
    DATASET_PATH, judge, load_cases, main, pass_hat_k,
)


def case(**overrides):
    base = {
        "id": "fetch-ok",
        "message": "Read page abc",
        "tools": ["notion-fetch", "notion-search"],
        "expected_tool": "notion-fetch",
        "args_contain": {"id": "abc"},
        "args_forbidden": ["cursor"],
        "notes": "test",
    }
    base.update(overrides)
    return base


def call(name="notion-fetch", **args):
    return {"name": name, "args": args}


def test_judge_accepts_expected_call_with_required_args():
    assert judge(case(), [call(id="abc")])


def test_judge_rejects_wrong_tool_missing_args_or_no_call():
    assert not judge(case(), [call("notion-search", query="abc")])
    assert not judge(case(), [call(id="other")])
    assert not judge(case(), [call()])
    assert not judge(case(), [])


def test_judge_rejects_forbidden_args_and_non_dict_args():
    assert not judge(case(), [call(id="abc", cursor="next")])
    assert not judge(case(), [{"name": "notion-fetch", "args": None}])


def test_judge_requires_every_call_to_match():
    assert judge(case(), [call(id="abc"), call(id="abc")])
    assert not judge(case(), [call(id="abc"), call("notion-search", query="abc")])


def test_judge_wildcard_means_present_and_strings_match_case_insensitively():
    wildcard = case(args_contain={"query": "*"}, args_forbidden=[])
    assert judge(wildcard, [call("notion-fetch", query="")])
    assert not judge(wildcard, [call("notion-fetch")])
    search = case(expected_tool="notion-search", args_contain={"query": "onboarding"},
                  args_forbidden=[])
    assert judge(search, [call("notion-search", query="Search: Onboarding checklist")])
    assert not judge(search, [call("notion-search", query="roadmap")])


def test_judge_null_expected_tool_means_no_tool_call():
    assert judge(case(expected_tool=None, args_contain={}), [])
    assert not judge(case(expected_tool=None, args_contain={}), [call(id="abc")])


def test_judge_accepts_tool_call_objects():
    assert judge(case(), [SimpleNamespace(name="notion-fetch", args={"id": "abc"})])


def test_pass_hat_k_is_binary_per_case():
    assert pass_hat_k(3, 3) == 1.0
    assert pass_hat_k(2, 3) == 0.0
    assert pass_hat_k(0, 1) == 0.0
    assert pass_hat_k([True, True, True], 3) == 1.0
    assert pass_hat_k([True, False, True], 3) == 0.0


@pytest.mark.parametrize("passes,trials", [(1, 0), (4, 3), (-1, 3), ([True], 2)])
def test_pass_hat_k_rejects_inconsistent_counts(passes, trials):
    with pytest.raises(ValueError):
        pass_hat_k(passes, trials)


def test_real_dataset_validates_and_covers_required_scenarios():
    cases = load_cases(DATASET_PATH)
    assert len(cases) == 12
    assert len({item["id"] for item in cases}) == len(cases)
    assert all(item["expected_tool"] is None or item["expected_tool"] in item["tools"]
               for item in cases)
    root = next(item for item in cases if item["id"] == "list-root-fr")
    assert root["expected_tool"] == "notion-list-private-pages"
    assert "cursor" in root["args_forbidden"]
    assert any(item["expected_tool"] is None for item in cases)


def write_cases(tmp_path, *cases):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in cases) + "\n\n")
    return path


def test_load_cases_accepts_blank_lines(tmp_path):
    loaded = load_cases(write_cases(tmp_path, case()))
    assert [item["id"] for item in loaded] == ["fetch-ok"]


def test_load_cases_rejects_schema_drift(tmp_path):
    missing = case()
    del missing["notes"]
    with pytest.raises(ValueError, match="missing keys"):
        load_cases(write_cases(tmp_path, missing))
    with pytest.raises(ValueError, match="expected_tool"):
        load_cases(write_cases(tmp_path, case(expected_tool="web_search")))
    with pytest.raises(ValueError, match="unknown tools"):
        load_cases(write_cases(tmp_path, case(tools=["not-a-tool"], expected_tool=None)))
    with pytest.raises(ValueError, match="duplicate id"):
        load_cases(write_cases(tmp_path, case(), case()))
    with pytest.raises(ValueError, match="forbidden argument"):
        load_cases(write_cases(tmp_path, case(args_forbidden=["id"])))
    with pytest.raises(ValueError, match="invalid JSON"):
        path = tmp_path / "bad.jsonl"
        path.write_text("{not json}\n")
        load_cases(path)


def test_default_run_validates_without_credentials(monkeypatch, capsys):
    monkeypatch.setattr("scripts.evaluate_tool_calls.Settings.from_env",
                        lambda: pytest.fail("credentials must not be created without --run"))
    assert main([]) == 0
    assert capsys.readouterr().out.strip() == "Dataset validated: 12 cases. No model calls."


@pytest.mark.parametrize("argv", [
    ["--run", "--trials", "0"],
    ["--run", "--trials", "9"],
    ["--run", "--limit", "0"],
    ["--run", "--limit", "13"],
])
def test_run_rejects_out_of_bounds_options_before_any_model_call(monkeypatch, argv):
    monkeypatch.setattr("scripts.evaluate_tool_calls.Settings.from_env",
                        lambda: pytest.fail("options must be validated before credentials"))
    with pytest.raises(SystemExit) as error:
        main(argv)
    assert error.value.code == 2
