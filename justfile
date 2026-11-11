# Common tasks. Install `just` (https://just.systems), then `just` lists them.
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install the Python and Node dependencies exactly as CI does.
setup:
    uv sync --locked --group dev
    cd pwa && npm ci

# Run the Python test suite. No test touches Azure.
test:
    uv run --locked pytest

# Lint and check formatting.
lint:
    uv run --locked ruff check .
    uv run --locked ruff format --check .

# Format the Python code.
fmt:
    uv run --locked ruff check . --fix
    uv run --locked ruff format .

# Check the documentation: links, anchors, ADR format, index, headings.
docs-check:
    python3 -m scripts.check_docs

# Everything CI checks for the Python side, plus the web client.
check: lint docs-check test pwa-check

# Test and build the web client.
pwa-check:
    cd pwa && npm test && npm run build

# Regenerate requirements.txt from uv.lock (CI fails when they diverge).
export-requirements:
    uv export --locked --no-dev --no-emit-project --no-hashes --format requirements-txt --output-file requirements.txt

# Run the agent locally on :8088 (needs .env and an authorized Azure session).
run:
    uv run --locked python main.py

# Build the backend image and run its smoke test.
bff-smoke:
    docker build -f Dockerfile.bff -t sa2-bff:ci .
    python3 scripts/smoke_test_bff.py sa2-bff:ci

# Validate the evaluation datasets without calling any model.
evals-validate:
    python3 scripts/evaluate_semantic_approval.py
    python3 -m scripts.evaluate_ssh_judge
    python3 -m scripts.evaluate_tool_calls
