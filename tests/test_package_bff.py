import json
import shutil
from pathlib import Path

import pytest

from scripts.component_changes import ROOT, load_manifest
from scripts.package_bff import package


def test_packaged_sources_match_bff_dependencies_and_exclude_agent(tmp_path):
    manifest = ROOT / ".github/components.json"
    package(ROOT, manifest, tmp_path)
    actual = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.py")}
    assert actual == set(load_manifest()["components"]["bff"]["source_files"])
    assert not (tmp_path / "src/savant/agent.py").exists()
    assert not (tmp_path / "src/savant/graph.py").exists()


def test_new_unregistered_local_import_fails_closed(tmp_path):
    root = tmp_path / "source"
    shutil.copytree(ROOT / "src/savant", root / "src/savant")
    source = root / "src/savant/oauth_callback.py"
    source.write_text(source.read_text() + "\nfrom savant import graph\n")
    with pytest.raises(ValueError, match="undeclared local source"):
        package(root, ROOT / ".github/components.json", tmp_path / "package")


def test_packaging_rejects_traversal(tmp_path):
    manifest = load_manifest()
    manifest["components"]["bff"]["source_files"] = ["src/../secrets.py"]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Invalid BFF source path"):
        package(ROOT, path, tmp_path / "package")
