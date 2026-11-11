"""Opt-in pass^k evaluation of tool selection and arguments.

Without --run, validate the dataset only; do not create credentials or a client.
Schemas are minimal and fictitious: they are never executed, only shown to the model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool

from savant.agent import MODEL_TOKEN_SCOPE, build_model
from savant.config import Settings

DATASET_PATH = Path(__file__).resolve().parents[1] / "evals" / "tool_calls.jsonl"

SYSTEM_PROMPT = (
    "You are Savant, a personal assistant with Notion and web tools. "
    "Call a tool when the request asks for an action or external information. "
    "If the request is ambiguous or its target is missing, ask one short clarifying question "
    "and do not call a tool. Never invent page ids."
)

REQUIRED_KEYS = {"id", "message", "tools", "expected_tool", "args_contain", "args_forbidden", "notes"}


async def _never_executed(**kwargs):
    # The evaluation only inspects the requested call; a real execution would be a bug.
    raise RuntimeError("evaluation tool schemas must never be executed")


def _tool(name: str, description: str, properties: dict, required: list[str]) -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=_never_executed,
        name=name,
        description=description,
        args_schema={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
    )


TOOLS = {
    "notion-list-private-pages": _tool(
        "notion-list-private-pages",
        "List the pages and databases at the root of the Notion workspace. "
        "cursor is only for pagination and must come from a previous response.",
        {
            "cursor": {"type": "string", "description": "Opaque pagination cursor from a previous call."},
            "limit": {"type": "integer", "description": "Maximum number of results."},
        },
        [],
    ),
    "notion-search": _tool(
        "notion-search",
        "Search Notion workspace content (pages and databases) by query.",
        {"query": {"type": "string", "description": "Text to search for in Notion."}, "page_size": {"type": "integer"}},
        ["query"],
    ),
    "notion-fetch": _tool(
        "notion-fetch",
        "Retrieve one Notion page or database by its id.",
        {"id": {"type": "string", "description": "Notion page or database id."}},
        ["id"],
    ),
    "notion-create-pages": _tool(
        "notion-create-pages",
        "Create one or more Notion pages. pages is an array of page objects.",
        {
            "pages": {
                "type": "array",
                "description": "Pages to create.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "parent": {"type": "object"},
                    },
                },
            }
        },
        ["pages"],
    ),
    "notion-delete-pages": _tool(
        "notion-delete-pages",
        "Permanently delete Notion pages. page_ids is an array of page ids.",
        {"page_ids": {"type": "array", "items": {"type": "string"}, "description": "Ids of the pages to delete."}},
        ["page_ids"],
    ),
    "web_search": _tool(
        "web_search",
        "Search the public web for current information.",
        {"query": {"type": "string", "description": "Search query."}},
        ["query"],
    ),
}


def _normalise(call) -> tuple[str | None, Mapping]:
    if isinstance(call, Mapping):
        return call.get("name"), call.get("args") or {}
    return getattr(call, "name", None), getattr(call, "args", None) or {}


def _args_match(args, expected: Mapping, forbidden: Sequence[str]) -> bool:
    if not isinstance(args, Mapping):
        return False
    if any(key in args for key in forbidden):
        return False
    for key, wanted in expected.items():
        if key not in args:
            return False
        if wanted == "*":
            continue
        actual = args[key]
        # Queries are free text: accept the expected term as a case-insensitive substring.
        if isinstance(wanted, str) and isinstance(actual, str):
            if wanted.casefold() not in actual.casefold():
                return False
        elif actual != wanted:
            return False
    return True


def judge(case: Mapping, tool_calls) -> bool:
    """A trial passes when every call matches the case and no call is unexpected."""
    calls = [_normalise(call) for call in (tool_calls or [])]
    if case["expected_tool"] is None:
        return not calls
    # One-shot selection: a chained call to another tool is not the expected behaviour.
    if not calls or any(name != case["expected_tool"] for name, _ in calls):
        return False
    return all(_args_match(args, case["args_contain"], case["args_forbidden"]) for _, args in calls)


def pass_hat_k(passes, trials: int) -> float:
    """Per-case pass^k: 1.0 only when all independent trials pass, else 0.0."""
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if isinstance(passes, Sequence) and not isinstance(passes, (str, bytes)):
        values = list(passes)
        if len(values) != trials:
            raise ValueError("passes length must equal trials")
        count = sum(bool(value) for value in values)
    else:
        count = int(passes)
    if not 0 <= count <= trials:
        raise ValueError("passed trials must be between 0 and trials")
    return 1.0 if count == trials else 0.0


def load_cases(path) -> list[dict]:
    """Read and validate the JSONL dataset, failing fast on schema drift."""
    cases, seen = [], set()
    for number, line in enumerate(Path(path).read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {number}: invalid JSON: {error}") from error
        missing = REQUIRED_KEYS - case.keys()
        if missing:
            raise ValueError(f"line {number}: missing keys {sorted(missing)}")
        if not isinstance(case["id"], str) or not case["id"]:
            raise ValueError(f"line {number}: id must be a non-empty string")
        if case["id"] in seen:
            raise ValueError(f"line {number}: duplicate id {case['id']!r}")
        seen.add(case["id"])
        if not isinstance(case["message"], str) or not case["message"].strip():
            raise ValueError(f"{case['id']}: message must be a non-empty string")
        if not isinstance(case["tools"], list) or not case["tools"]:
            raise ValueError(f"{case['id']}: tools must be a non-empty list")
        unknown = set(case["tools"]) - TOOLS.keys()
        if unknown:
            raise ValueError(f"{case['id']}: unknown tools {sorted(unknown)}")
        if case["expected_tool"] is not None and case["expected_tool"] not in case["tools"]:
            raise ValueError(f"{case['id']}: expected_tool must be one of the offered tools or null")
        if not isinstance(case["args_contain"], dict):
            raise ValueError(f"{case['id']}: args_contain must be an object")
        if not isinstance(case["args_forbidden"], list):
            raise ValueError(f"{case['id']}: args_forbidden must be a list")
        if set(case["args_contain"]) & set(case["args_forbidden"]):
            raise ValueError(f"{case['id']}: a forbidden argument cannot also be expected")
        if not isinstance(case["notes"], str):
            raise ValueError(f"{case['id']}: notes must be a string")
        cases.append(case)
    if not cases:
        raise ValueError("dataset is empty")
    return cases


async def evaluate(cases, settings, trials: int) -> int:
    # One credential and token provider for the whole run, like a hosted process.
    token_provider = get_bearer_token_provider(DefaultAzureCredential(), MODEL_TOKEN_SCOPE)
    results = []
    for case in cases:
        model = build_model(settings, [TOOLS[name] for name in case["tools"]], token_provider=token_provider)
        passes = 0
        for _ in range(trials):
            response = await model.ainvoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=case["message"]),
                ]
            )
            passes += judge(case, getattr(response, "tool_calls", None))
        results.append(
            {
                "id": case["id"],
                "trials": trials,
                "passes": passes,
                "pass_at_1": round(passes / trials, 3),
                "pass_hat_k": pass_hat_k(passes, trials),
            }
        )
        print(json.dumps(results[-1]))
    mean_at_1 = sum(result["pass_at_1"] for result in results) / len(results)
    mean_hat_k = sum(result["pass_hat_k"] for result in results) / len(results)
    failed = [result["id"] for result in results if result["pass_hat_k"] < 1.0]
    print(
        json.dumps(
            {
                "cases": len(results),
                "trials": trials,
                "mean_pass_at_1": round(mean_at_1, 3),
                "mean_pass_hat_k": round(mean_hat_k, 3),
                "failed_cases": failed,
                "validation": "live model inference only; schemas are fictitious and never executed",
            }
        )
    )
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Make paid inference calls using existing Entra credentials")
    parser.add_argument("--trials", type=int, default=3, help="Independent attempts per case (1-8, default 3)")
    parser.add_argument("--limit", type=int, help="Evaluate only the first N cases")
    args = parser.parse_args(argv)
    if not 1 <= args.trials <= 8:
        parser.error("--trials must be between 1 and 8")
    cases = load_cases(DATASET_PATH)
    if args.limit is not None and not 1 <= args.limit <= len(cases):
        parser.error(f"--limit must be between 1 and {len(cases)}")
    if not args.run:
        print(f"Dataset validated: {len(cases)} cases. No model calls.")
        return 0
    settings = Settings.from_env()  # Fail before creating any credential/client.
    return asyncio.run(evaluate(cases[: args.limit], settings, args.trials))


if __name__ == "__main__":
    raise SystemExit(main())
