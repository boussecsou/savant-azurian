"""Validate the deployed Responses result without printing caller data."""

import json
import os
import re
import subprocess
import sys
import time

from savant.health import RUNTIME_SMOKE_EXPECTED, RUNTIME_SMOKE_PROMPT


def validate_response(raw):
    """Accept only HTTP success and a completed, exact model text response."""
    match = re.search(r"HTTP/\S+\s+(\d{3})[^\n]*\r?\n", raw)
    if not match or int(match[1]) != 200:
        raise ValueError("The runtime did not return HTTP 200.")
    http = raw[match.end() :].replace("\r\n", "\n")
    _, separator, body = http.partition("\n\n")
    if not separator:
        raise ValueError("Missing HTTP response body.")
    if body.lstrip().startswith("data:") or "\ndata:" in body:
        events = [
            json.loads(line[5:].strip())
            for line in body.splitlines()
            if line.startswith("data:") and line[5:].strip() != "[DONE]"
        ]
        completed = [event["response"] for event in events if event.get("type") == "response.completed"]
        if len(completed) != 1:
            raise ValueError("Missing completed Responses event.")
        response = completed[0]
    else:
        response = json.loads(body)
    if response.get("status") != "completed" or response.get("error"):
        raise ValueError("The model response did not complete successfully.")
    output = response.get("output", [])
    if not output or any(item.get("type") not in {"message", "reasoning"} for item in output):
        raise ValueError("Unexpected tool or approval output in the runtime probe.")
    text = "".join(
        part.get("text", "")
        for item in output
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )
    if text.strip() != RUNTIME_SMOKE_EXPECTED:
        raise ValueError("The expected model probe text was not returned.")


def main():
    version = os.environ.get("DEPLOYED_AGENT_VERSION", "")
    if not re.fullmatch(r"[0-9]+", version):
        print("::error::Missing valid deployed agent version.")
        return 1
    started = time.monotonic()
    try:
        result = subprocess.run(
            [
                "azd",
                "ai",
                "agent",
                "invoke",
                "sa2-agent",
                RUNTIME_SMOKE_PROMPT,
                "--version",
                version,
                "--protocol",
                "responses",
                "--new-session",
                "--new-conversation",
                "--timeout",
                "180",
                "--output",
                "raw",
            ],
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode:
            raise ValueError("Remote invocation failed; inspect the targeted agent session privately.")
        validate_response(result.stdout)
    except (ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        # Never echo server bodies, stderr, consent URLs, headers or session IDs.
        print("::error::Runtime/model smoke test failed; response details are intentionally omitted.")
        return 1
    summary = f"Runtime/model smoke test passed: sa2-agent v{version}, {time.monotonic() - started:.1f}s."
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(f"\n{summary}\n\nPersonal Toolbox OAuth is validated manually by the user.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
