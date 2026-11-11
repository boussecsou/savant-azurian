"""Compatibility NUL-path interface backed by the shared component registry."""

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.component_changes import classify


def requires_agent_deploy(paths: list[str]) -> bool:
    # Preserve this legacy interface's interpretation of absent input as unknown.
    return not paths or classify(paths)["agent"]["runtime"]


if __name__ == "__main__":
    paths = [part.decode("utf-8") for part in sys.stdin.buffer.read().split(b"\0") if part]
    print("true" if requires_agent_deploy(paths) else "false")
