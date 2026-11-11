"""Compatibility entry point; ownership and release planning live under scripts/."""

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.component_changes import classify
from scripts.release_plan import api
from scripts.release_plan import changed_since as component_changed_since
from scripts.release_plan import last_checkpoint as component_checkpoint


def requires_publication(paths: list[str]) -> bool:
    return classify(paths)["bff"]["runtime"]


def changed_since(base: str | None, sha: str) -> bool:
    return component_changed_since(base, sha, "bff")


def last_checkpoint(repository: str, current_run: str, request=api) -> str | None:
    return component_checkpoint(repository, current_run, "bff", "publish-bff.yml", request)


if __name__ == "__main__":
    from scripts.release_plan import main

    sys.argv = [sys.argv[0], "--component", "bff"]
    main()
