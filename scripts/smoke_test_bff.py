"""Run the built BFF image with synthetic local configuration, without Azure."""

import base64
import json
import os
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


def docker(*args, env=None):
    result = subprocess.run(["docker", *args], env=env, capture_output=True, text=True, timeout=30)
    if result.returncode:
        # Never print captured output: container logs/config can hold secrets.
        raise RuntimeError("BFF Docker validation command failed.")
    return result.stdout.strip()


def main():
    image = sys.argv[1] if len(sys.argv) > 1 else "sa2-bff:ci"
    environment = os.environ.copy()
    environment["NOTION_OAUTH_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
    container = docker(
        "run",
        "--detach",
        "--rm",
        "--publish",
        "127.0.0.1::8090",
        "--env",
        "NOTION_OAUTH_ENCRYPTION_KEY",
        "--env",
        "NOTION_OAUTH_CALLBACK_URL=http://127.0.0.1:8090/oauth/notion/callback",
        "--env",
        "NOTION_OAUTH_STORE_URL=sqlite:///tmp/bff-smoke/oauth.db",
        image,
        env=environment,
    )
    try:
        port = docker("port", container, "8090/tcp").rsplit(":", 1)[1]
        deadline = time.monotonic() + 60
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{port}/readiness", timeout=3) as response:
                    if response.status != 200 or json.load(response) != {"status": "ready"}:
                        raise RuntimeError("BFF readiness response is invalid.")
                break
            except (URLError, TimeoutError, ConnectionError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("BFF image did not become ready.") from None
                time.sleep(1)
        docker(
            "exec",
            container,
            "python",
            "-c",
            "from importlib.metadata import distributions; "
            "assert 'azure-keyvault-secrets' not in {d.metadata['Name'].lower() for d in distributions()}",
        )
        print("BFF image: /readiness HTTP 200, port 8090 exposed, Key Vault SDK absent.")
    finally:
        subprocess.run(["docker", "rm", "--force", container], capture_output=True, timeout=30)


if __name__ == "__main__":
    main()
