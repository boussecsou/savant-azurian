"""Check the tools this repository needs, and say how to get the ones that are missing.

    python3 -m scripts.doctor          # or: just doctor

Read-only: it only runs `--version` style commands. Exit status 1 only when a **required** tool is missing
or too old; optional tools (for deployment, containers, releases) are reported as hints.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

Runner = Callable[[list[str]], str | None]


@dataclass(frozen=True)
class Tool:
    name: str
    command: list[str]
    needed_for: str
    install: str
    required: bool = False
    minimum: tuple[int, ...] | None = None


TOOLS = [
    Tool("uv", ["uv", "--version"], "Python environment and tests", "https://docs.astral.sh/uv/", True),
    Tool("node", ["node", "--version"], "web client", "https://nodejs.org (22 or later)", True, (22,)),
    Tool("npm", ["npm", "--version"], "web client", "ships with Node"),
    Tool("just", ["just", "--version"], "task shortcuts (`just check`)", "https://just.systems"),
    Tool("docker", ["docker", "--version"], "backend image smoke test", "https://docs.docker.com/get-docker/"),
    Tool(
        "az",
        ["az", "version", "--output", "tsv"],
        "deployment (Azure CLI)",
        "https://learn.microsoft.com/cli/azure/install-azure-cli",
    ),
    Tool("bicep", ["az", "bicep", "version"], "compiling infra/ (`az bicep install`)", "az bicep install"),
    Tool("azd", ["azd", "version"], "deployment (Azure Developer CLI)", "https://aka.ms/install-azd"),
    Tool("gh", ["gh", "--version"], "GitHub variables and releases", "https://cli.github.com/"),
]


def parse_version(text: str) -> tuple[int, ...] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(part) for part in match.groups(default="0")) if match else None


def run(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (done.stdout + done.stderr) if done.returncode == 0 else None


def check_python(version: tuple[int, ...] = tuple(sys.version_info[:3])) -> tuple[bool, str]:
    return version >= (3, 13), f"Python {'.'.join(map(str, version))} (3.13 required)"


def check_tool(tool: Tool, runner: Runner = run) -> tuple[bool, str]:
    output = runner(tool.command)
    if output is None:
        return False, "not found"
    version = parse_version(output)
    if tool.minimum and (version is None or version < tool.minimum):
        wanted = ".".join(map(str, tool.minimum))
        return False, f"{'.'.join(map(str, version or ()))} found, {wanted} or later needed"
    return True, ".".join(map(str, version)) if version else "found"


def check_foundry_extension(runner: Runner = run) -> tuple[bool, str]:
    output = runner(["azd", "extension", "list", "--installed"])
    if output is None:
        return False, "azd not available"
    return (
        "microsoft.foundry" in output
    ), "installed" if "microsoft.foundry" in output else "run: azd extension install microsoft.foundry"


def report(runner: Runner = run) -> tuple[list[str], bool]:
    lines, failed = [], False
    ok, detail = check_python()
    lines.append(f"{'ok ' if ok else 'FAIL'}  python      {detail}")
    failed |= not ok
    for tool in TOOLS:
        ok, detail = check_tool(tool, runner)
        mark = "ok " if ok else ("FAIL" if tool.required else "--  ")
        lines.append(f"{mark}  {tool.name:<10}  {detail}" + ("" if ok else f"  [{tool.needed_for}: {tool.install}]"))
        failed |= tool.required and not ok
    if check_tool(TOOLS[0], runner)[0] and runner(["azd", "version"]) is not None:
        ok, detail = check_foundry_extension(runner)
        lines.append(f"{'ok ' if ok else '--  '}  azd ext     microsoft.foundry: {detail}")
    return lines, failed


def main() -> int:
    lines, failed = report()
    print("\n".join(lines))
    print(
        "\nSome required tools are missing."
        if failed
        else "\nThe required tools are in place. `-- ` lines are optional."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
