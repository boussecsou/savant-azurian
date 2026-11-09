"""One declarative ownership policy for CI, release planning and BFF packaging."""
from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ".github/components.json"


def _valid_paths(paths) -> bool:
    return isinstance(paths, list) and all(
        isinstance(p, str) and p and not p.startswith("/") and ".." not in p.split("/") for p in paths
    )


def load_manifest(path: Path | None = None) -> dict:
    data = json.loads((path or ROOT / MANIFEST).read_text())
    if data.get("version") != 1 or not isinstance(data.get("components"), dict) or not data["components"]:
        raise ValueError("Invalid component registry version or components")
    for name, component in data["components"].items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise ValueError("Invalid component name")
        if not re.fullmatch(r"[a-z0-9_-]+\.yml", component.get("workflow", "")):
            raise ValueError("Invalid release workflow")
        for field in ("runtime", "exclude", "source_files", "ci"):
            if not _valid_paths(component.get(field)):
                raise ValueError(f"Invalid {field} paths for {name}")
        if any(not p.startswith("src/") or any(c in p for c in "*?[") for p in component["source_files"]):
            raise ValueError("Packaged sources must be explicit files under src/")
    if not isinstance(data.get("non_runtime"), list) or any(not isinstance(p, str) for p in data["non_runtime"]):
        raise ValueError("Invalid non-runtime paths")
    # CI-only checks (e.g. the local PWA) have no release workflow and never deliver.
    checks = data.setdefault("checks", {})
    if not isinstance(checks, dict) or any(
        not re.fullmatch(r"[a-z][a-z0-9_-]*", name) or name in data["components"] or not _valid_paths(paths)
        for name, paths in checks.items()
    ):
        raise ValueError("Invalid CI-only checks")
    return data


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def classify(paths: list[str], manifest: dict | None = None) -> dict:
    manifest = manifest or load_manifest()
    result = {name: {"runtime": False, "ci": False} for name in manifest["components"]}
    for path in paths:
        if not path:
            continue
        known = path == MANIFEST or matches(path, manifest["non_runtime"])
        for name, component in manifest["components"].items():
            runtime = path == MANIFEST or (
                matches(path, component["runtime"] + component["source_files"])
                and not matches(path, component["exclude"])
            )
            ci = runtime or matches(path, component["ci"])
            known = known or runtime or ci
            result[name]["runtime"] |= runtime
            result[name]["ci"] |= ci
        if not known:
            # A newly introduced, unowned runtime/configuration cannot silently ship nowhere.
            for impact in result.values():
                impact.update(runtime=True, ci=True)
    return result


def classify_checks(paths: list[str], manifest: dict | None = None) -> dict:
    manifest = manifest or load_manifest()
    return {name: any(p and matches(p, patterns) for p in paths) for name, patterns in manifest["checks"].items()}


def changed_paths(base: str, head: str) -> list[str]:
    # Disable rename detection so both removed and added ownership boundaries count.
    output = subprocess.check_output(["git", "diff", "--name-only", "--no-renames", "-z", base, head])
    return [os.fsdecode(p) for p in output.split(b"\0") if p]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    manifest = load_manifest()
    try:
        paths = changed_paths(args.base, args.head)
        impact = classify(paths, manifest)
        checks = classify_checks(paths, manifest)
    except subprocess.CalledProcessError:
        impact = {name: {"runtime": True, "ci": True} for name in manifest["components"]}
        checks = dict.fromkeys(manifest["checks"], True)
    print(json.dumps({**impact, "checks": checks}, sort_keys=True))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as stream:
            for name, flags in impact.items():
                for kind, affected in flags.items():
                    stream.write(f"{name}_{kind}={str(affected).lower()}\n")
            for name, affected in checks.items():
                stream.write(f"{name}_ci={str(affected).lower()}\n")


if __name__ == "__main__":
    main()
