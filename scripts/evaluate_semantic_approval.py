"""Opt-in real-model consent evaluation, measured with pass^k. No graph, OAuth or external tools.

Without --run, validate the dataset only; do not create credentials or a client.
A case passes only when every one of its --trials answers is expected (pass^k): a judge that
says yes four times out of five still loops the owner on the fifth. Judge failures
(rate limit, timeout...) are counted apart, so a 429 is never mistaken for a hesitant judge.
"""

import argparse
import asyncio
import json
import logging
from collections import Counter
from pathlib import Path

DATASET_PATH = Path(__file__).resolve().parents[1] / "evals" / "semantic_approval.jsonl"
DECISIONS = {"APPROVE", "REJECT", "CLARIFY"}
MAX_TRIALS = 10


def load_cases(path, required, decisions):
    """Read the JSONL dataset; `expected` is one decision or a list of acceptable ones."""
    cases, seen = [], set()
    for number, line in enumerate(Path(path).read_text().splitlines(), start=1):
        if not line.strip():
            continue
        case = json.loads(line)
        missing = set(required) - case.keys()
        if missing:
            raise ValueError(f"line {number}: missing keys {sorted(missing)}")
        if case["id"] in seen:
            raise ValueError(f"line {number}: duplicate id {case['id']!r}")
        seen.add(case["id"])
        expected = case["expected"] if isinstance(case["expected"], list) else [case["expected"]]
        if not expected or set(expected) - decisions:
            raise ValueError(f"{case['id']}: expected must be among {sorted(decisions)}")
        cases.append({**case, "expected": expected})
    if not cases:
        raise ValueError("dataset is empty")
    return cases


class _Failures(logging.Handler):
    """Counts the judges' own fail-closed logs (approval_judge_failed, ssh_judge_failed)."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.reasons = Counter()

    def emit(self, record):
        message = record.getMessage()
        if "_judge_failed" in message:
            self.reasons[message.rsplit("reason=", 1)[-1]] += 1


async def run_trials(cases, judge_one, trials, concurrency=3):
    """Run every case `trials` times; print one line per case and a summary. Nonzero if any fails."""
    failures = _Failures()
    logging.getLogger("savant").addHandler(failures)
    gate = asyncio.Semaphore(concurrency)

    async def bounded(case):
        async with gate:
            return await judge_one(case)

    try:
        answers = await asyncio.gather(*(bounded(case) for case in cases for _ in range(trials)))
    finally:
        logging.getLogger("savant").removeHandler(failures)
    failed = []
    for index, case in enumerate(cases):
        got = answers[index * trials : (index + 1) * trials]
        passed = all(answer in case["expected"] for answer in got)
        if not passed:
            failed.append(case["id"])
        print(
            json.dumps(
                {
                    "id": case["id"],
                    "expected": case["expected"],
                    "answers": dict(Counter(got)),
                    "pass_hat_k": 1.0 if passed else 0.0,
                },
                ensure_ascii=False,
            )
        )
    print(
        json.dumps(
            {
                "cases": len(cases),
                "trials": trials,
                "failed_cases": failed,
                "judge_failures": dict(failures.reasons),
                "validation": "live model inference only; no Foundry host, Notion or VM",
            }
        )
    )
    return 1 if failed else 0


def arguments(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--run", action="store_true", help="Make paid inference calls using existing Entra credentials")
    parser.add_argument("--limit", type=int, default=0, help="Only the first N cases (0: all)")
    parser.add_argument("--trials", type=int, default=3, help=f"Answers per case, 1 to {MAX_TRIALS} (pass^k)")
    args = parser.parse_args()
    if not 1 <= args.trials <= MAX_TRIALS:
        parser.error(f"--trials must be between 1 and {MAX_TRIALS}")
    if args.limit < 0:
        parser.error("--limit must be positive")
    return args


def main():
    args = arguments(__doc__)
    cases = load_cases(DATASET_PATH, ("id", "operation", "proposal", "message", "expected"), DECISIONS)
    cases = cases[: args.limit] if args.limit else cases
    if not args.run:
        print(
            f"Dataset validated: {len(cases)} cases. No model calls. Use --run only after authorizing inference/authentication."
        )
        return 0
    from savant.agent import build_model
    from savant.config import Settings
    from savant.semantic_approval import SemanticApprovalGuardrail

    settings = Settings.from_env()  # Fail before creating any credential/client.
    guardrail = SemanticApprovalGuardrail(
        build_model(settings, (), guardrail=True), timeout=settings.semantic_approval_timeout
    )
    print(json.dumps({"deployment": settings.semantic_approval_model or settings.model_deployment_name}))

    async def judge_one(case):
        return await guardrail.evaluate(
            operation=case["operation"],
            proposal=case["proposal"],
            user_message=case["message"],
            context=case.get("context"),
        )

    return asyncio.run(run_trials(cases, judge_one, args.trials))


if __name__ == "__main__":
    raise SystemExit(main())
