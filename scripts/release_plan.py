"""Plan a component release from its last successful checkpoint, before Azure login."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

from .component_changes import changed_paths, classify, load_manifest


def api(endpoint: str):
    return json.loads(subprocess.check_output(["gh", "api", endpoint], text=True))


def last_checkpoint(repository: str, current_run: str, component: str, workflow: str, request=api) -> str | None:
    pattern = re.compile(rf"(?:release-{re.escape(component)}|{re.escape(component)}-checkpoint)-([0-9a-f]{{40}})\Z")
    page = 1
    while True:
        runs = request(
            f"repos/{repository}/actions/workflows/{workflow}/runs?branch=main&status=success&per_page=100&page={page}"
        )["workflow_runs"]
        for run in runs:
            if str(run["id"]) == current_run:
                continue
            artifact_page = 1
            while True:
                artifacts = request(
                    f"repos/{repository}/actions/runs/{run['id']}/artifacts?per_page=100&page={artifact_page}"
                )["artifacts"]
                for artifact in artifacts:
                    match = pattern.fullmatch(artifact["name"])
                    if match and not artifact["expired"]:
                        return match[1]
                if len(artifacts) < 100:
                    break
                artifact_page += 1
        if len(runs) < 100:
            return None
        page += 1


def changed_since(base: str | None, sha: str, component: str) -> bool:
    if base is None:
        return True
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", base, sha], capture_output=True)
    if ancestry.returncode:
        # Includes expired/unavailable history and divergent histories: never miss a release.
        return True
    return classify(changed_paths(base, sha))[component]["runtime"]


def _has_successful_ci(repository: str, sha: str, request) -> bool:
    page = 1
    while True:
        runs = request(
            f"repos/{repository}/actions/workflows/ci.yml/runs?head_sha={sha}&branch=main&event=push&per_page=100&page={page}"
        )["workflow_runs"]
        if any(
            run.get("head_sha") == sha
            and run.get("head_branch") == "main"
            and run.get("event") == "push"
            and run.get("conclusion") == "success"
            and run.get("head_repository", {}).get("full_name") == repository
            for run in runs
        ):
            return True
        if len(runs) < 100:
            return False
        page += 1


def verify_ci(repository: str, sha: str, request=api, attempts: int = 6, delay: float = 5.0, sleep=time.sleep):
    """Require a green push CI for this exact SHA.

    CD and Publish BFF start via workflow_run a few seconds after CI ends, and the
    API can lag behind. Retry briefly so that lag is not mistaken for a missing CI.
    The query must not use `status=success`: GitHub's index for that filter can stay
    stale for many minutes (observed on 75845eb), while `conclusion` is checked below.
    """
    for attempt in range(attempts):
        if _has_successful_ci(repository, sha, request):
            return
        if attempt < attempts - 1:
            sleep(delay)
    raise RuntimeError("This SHA has no successful push CI on main in this repository")


def plan(component: str) -> dict:
    manifest = load_manifest()
    definition = manifest["components"][component]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    repository = os.environ["GITHUB_REPOSITORY"]
    # Checkout deliberately does not persist git credentials. Use GH_TOKEN for
    # this read so private repositories work without enabling credential reuse.
    main = api(f"repos/{repository}/git/ref/heads/main")["object"]["sha"]
    if sha != main:
        return {"sha": sha, "release": False, "eligible": False, "reason": "superseded-main", "base": ""}
    verify_ci(repository, sha)
    manual = os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
    base = (
        None if manual else last_checkpoint(repository, os.environ["GITHUB_RUN_ID"], component, definition["workflow"])
    )
    release = manual or changed_since(base, sha, component)
    return {
        "sha": sha,
        "release": release,
        "eligible": True,
        "reason": "manual" if manual else ("runtime-changed-or-no-baseline" if release else "runtime-unchanged"),
        "base": base or "",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=load_manifest()["components"], required=True)
    args = parser.parse_args()
    result = plan(args.component)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        for key, value in result.items():
            output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
        summary.write(f"### {args.component} release plan\n\n```json\n{json.dumps(result, indent=2)}\n```\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
