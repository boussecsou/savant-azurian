# Common tasks. Install `just` (https://just.systems), then `just` lists them.
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Check that the tools this repository needs are installed (read-only).
doctor:
    python3 -m scripts.doctor

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

# Build and lint the Bicep template and its parameter file (needs the Azure CLI).
infra-check:
    az bicep build --file infra/main.bicep --stdout > /dev/null
    for f in infra/main.bicep infra/modules/*.bicep; do az bicep lint --file "$f"; done
    AZURE_ENV_NAME=savant-dev AZURE_LOCATION=italynorth az bicep build-params --file infra/main.bicepparam --stdout > /dev/null

# Test and build the web client.
pwa-check:
    cd pwa && npm test && npm run build

# Regenerate the PDF guides from their Markdown (needs Chromium; the `markdown` package is fetched on the fly).
docs-pdf:
    uv run --no-project --with markdown python -m scripts.build_pdf docs/user-guide.md docs/user-guide.pdf
    uv run --no-project --with markdown python -m scripts.build_pdf docs/deployment.md docs/deployment.pdf

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
