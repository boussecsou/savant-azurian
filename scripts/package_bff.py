"""Copy the BFF source closure declared in the shared component registry."""

import argparse
import ast
import json
import shutil
from pathlib import Path


def package(source_root: Path, manifest: Path, destination: Path):
    paths = json.loads(manifest.read_text())["components"]["bff"]["source_files"]
    selected = set(paths)
    for relative in paths:
        if not relative.startswith("src/") or ".." in relative.split("/"):
            raise ValueError("Invalid BFF source path")
        source = source_root / relative
        module = relative.removeprefix("src/").removesuffix(".py").split("/")
        for node in ast.walk(ast.parse(source.read_text())):
            imports = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = module[: -node.level] if node.level else []
                stem = prefix + (node.module.split(".") if node.module else [])
                imports = [".".join(stem), *[".".join(stem + [alias.name]) for alias in node.names]]
            for imported in imports:
                if imported == "savant" or imported.startswith("savant."):
                    base = "src/" + imported.replace(".", "/")
                    candidates = [base + ".py", base + "/__init__.py"]
                    found = next((p for p in candidates if (source_root / p).is_file()), None)
                    if found and found not in selected:
                        raise ValueError(f"BFF imports an undeclared local source: {found}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=Path(".github/components.json"))
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    package(args.source_root, args.manifest, args.destination)
