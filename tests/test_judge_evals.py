"""Offline checks of the judge evaluations: datasets and pass^k, no model call, no credential."""
import asyncio
import json
import logging

import pytest

from scripts.evaluate_semantic_approval import DATASET_PATH, DECISIONS, load_cases, run_trials
from scripts.evaluate_ssh_judge import DATASET_PATH as SSH_DATASET, REQUIRED, VERDICTS


def test_both_datasets_are_valid_and_cover_the_observed_cases():
    consent = load_cases(DATASET_PATH, ("id", "operation", "proposal", "message", "expected"), DECISIONS)
    assert {"voice-delete-exactement", "voice-delete-oui"} <= {case["id"] for case in consent}
    ssh = load_cases(SSH_DATASET, REQUIRED, VERDICTS)
    kinds = {case["id"].split("-")[0] for case in ssh}
    assert {"read", "add", "del", "set", "compound", "overwrite", "injected", "secret"} <= kinds
    # Issue #51: a read after a web search must run.
    assert next(c for c in ssh if c["id"] == "read-after-web")["expected"] == ["RUN"]


def test_load_cases_rejects_unknown_labels_and_duplicates(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"id": "a", "expected": "MAYBE"}) + "\n")
    with pytest.raises(ValueError):
        load_cases(path, ("id", "expected"), DECISIONS)
    path.write_text((json.dumps({"id": "a", "expected": "APPROVE"}) + "\n") * 2)
    with pytest.raises(ValueError):
        load_cases(path, ("id", "expected"), DECISIONS)


def test_a_case_passes_only_when_every_trial_does_and_judge_failures_are_counted(capsys):
    cases = [{"id": "steady", "expected": ["APPROVE"]}, {"id": "flaky", "expected": ["APPROVE"]}]
    answers = {"steady": iter(["APPROVE"] * 3), "flaky": iter(["APPROVE", "CLARIFY", "APPROVE"])}

    async def judge_one(case):
        if case["id"] == "flaky":
            logging.getLogger("savant.semantic_approval").warning("approval_judge_failed reason=%s", "timeout")
        return next(answers[case["id"]])

    assert asyncio.run(run_trials(cases, judge_one, 3)) == 1
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["failed_cases"] == ["flaky"] and summary["judge_failures"] == {"timeout": 3}
