"""Opt-in real-model evaluation of the SSH command judge, measured with pass^k.

Without --run, validate the dataset only; do not create credentials or a client. No command
ever reaches a VM: only the judge is called. Run from the repository root:
    python -m scripts.evaluate_ssh_judge [--run --trials 5]
"""

import asyncio
import json
from pathlib import Path

from .evaluate_semantic_approval import arguments, load_cases, run_trials

DATASET_PATH = Path(__file__).resolve().parents[1] / "evals" / "ssh_commands.jsonl"
VERDICTS = {"RUN", "CONFIRM", "REFUSE"}
REQUIRED = ("id", "command", "reason", "owner_message", "outside_content", "expected")


def main():
    args = arguments(__doc__)
    cases = load_cases(DATASET_PATH, REQUIRED, VERDICTS)
    cases = cases[: args.limit] if args.limit else cases
    if not args.run:
        print(
            f"Dataset validated: {len(cases)} cases. No model calls. Use --run only after authorizing inference/authentication."
        )
        return 0
    from savant.agent import build_model
    from savant.config import Settings
    from savant.tools.ssh import CommandJudge

    settings = Settings.from_env()  # Fail before creating any credential/client.
    judge = CommandJudge(build_model(settings, (), guardrail=True), timeout=settings.semantic_approval_timeout)
    print(json.dumps({"deployment": settings.semantic_approval_model or settings.model_deployment_name}))

    async def judge_one(case):
        return await judge.judge(
            command=case["command"],
            reason=case["reason"],
            owner_message=case["owner_message"],
            outside_content=case["outside_content"],
        )

    return asyncio.run(run_trials(cases, judge_one, args.trials))


if __name__ == "__main__":
    raise SystemExit(main())
