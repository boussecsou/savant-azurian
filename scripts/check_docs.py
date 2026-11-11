"""Check the documentation: links, anchors, ADR format, index completeness and heading language.

Fast, offline and dependency-free, so it runs in the pre-commit hook and in CI:

    python3 -m scripts.check_docs

Exit status 1 and one line per problem when something is wrong.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TOP_LEVEL = ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md")
ADR_STATUSES = {"Proposed", "Accepted", "Deprecated", "Superseded"}
FRENCH_LETTERS = re.compile("[éèêëàâùûçôîï]")
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCE = re.compile(r"^(```|~~~)")


def markdown_files(root: Path) -> list[Path]:
    files = [root / name for name in TOP_LEVEL if (root / name).exists()]
    files += sorted((root / "docs").rglob("*.md"))
    return files


def headings(path: Path) -> list[str]:
    """Headings of a Markdown file, ignoring fenced code blocks."""
    found, fenced = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and line.startswith("#"):
            found.append(re.sub(r"^#+\s*", "", line).strip())
    return found


def slug(heading: str) -> str:
    """The anchor GitHub generates for a heading."""
    text = re.sub(r"[`*_]", "", heading.lower())
    return re.sub(r"[^\w\- ]", "", text).strip().replace(" ", "-")


def links(path: Path) -> list[str]:
    found, fenced = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            # Inline code can show a link as an example; it is not a link.
            found += LINK.findall(re.sub(r"`[^`]*`", "", line))
    return found


def check_links(root: Path, files: list[Path]) -> list[str]:
    problems = []
    for path in files:
        for target in links(path):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            name, _, anchor = target.partition("#")
            destination = (path.parent / name).resolve() if name else path
            where = path.relative_to(root)
            if not destination.exists():
                problems.append(f"{where}: broken link {target}")
            elif anchor and destination.suffix == ".md" and anchor not in {slug(h) for h in headings(destination)}:
                problems.append(f"{where}: no heading for the anchor {target}")
    return problems


def field(text: str, name: str) -> str | None:
    match = re.search(rf"^- \*\*{name}:\*\*\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def check_adrs(root: Path) -> list[str]:
    folder = root / "docs" / "adr"
    if not folder.exists():
        return []
    problems, index = [], (folder / "README.md").read_text(encoding="utf-8")
    for path in sorted(folder.glob("[0-9][0-9][0-9][0-9]-*.md")):
        text, number = path.read_text(encoding="utf-8"), path.name[:4]
        where = path.relative_to(root)
        if not re.match(rf"# ADR-{number}: \S", text):
            problems.append(f"{where}: the title must start with '# ADR-{number}: '")
        for name in ("Status", "Date", "Tags"):
            if field(text, name) is None:
                problems.append(f"{where}: missing '- **{name}:**'")
        status = (field(text, "Status") or "").split(" ")[0]
        if status not in ADR_STATUSES:
            problems.append(f"{where}: status must start with one of {sorted(ADR_STATUSES)}")
        date = field(text, "Date") or ""
        if not re.match(r"\d{4}-\d{2}-\d{2}", date):
            problems.append(f"{where}: the date must start with YYYY-MM-DD")
        row = re.search(rf"^\| \[{number}\]\({re.escape(path.name)}\) \|.*\| (.+?) \|$", index, re.MULTILINE)
        if not row:
            problems.append(f"docs/adr/README.md: {path.name} is missing from the index")
        elif not row.group(1).strip("* ").startswith(status):
            problems.append(f"docs/adr/README.md: the index status of {number} differs from the file ({status})")
    numbers = [p.name[:4] for p in folder.glob("[0-9][0-9][0-9][0-9]-*.md")]
    if len(numbers) != len(set(numbers)):
        problems.append("docs/adr: two ADRs share a number")
    return problems


def check_designs(root: Path) -> list[str]:
    folder = root / "docs" / "design"
    problems = []
    for path in sorted(folder.glob("s[pd][ec]*-*.md")) if folder.exists() else []:
        text, where = path.read_text(encoding="utf-8"), path.relative_to(root)
        if field(text, "Status") is None:
            problems.append(f"{where}: missing '- **Status:**'")
        if path.name.startswith("sdd-") and "## Revision history" not in text:
            problems.append(f"{where}: a design document ends with '## Revision history'")
    return problems


def check_orphans(root: Path) -> list[str]:
    """Every document under docs/ must be reachable from an index."""
    indexes = [root / "docs" / "README.md", root / "docs" / "design" / "README.md", root / "docs" / "adr" / "README.md"]
    reached = set()
    for index in indexes:
        if index.exists():
            for target in links(index):
                name = target.partition("#")[0]
                if name and not target.startswith(("http", "mailto:")):
                    reached.add((index.parent / name).resolve())
    problems = []
    for path in sorted((root / "docs").rglob("*.md")):
        if path.name in {"README.md", "template.md"} or path.resolve() in reached:
            continue
        problems.append(f"{path.relative_to(root)}: not linked from any documentation index")
    return problems


def check_language(root: Path, files: list[Path]) -> list[str]:
    """Headings and file names are English. Quoted French (runtime phrases) is fine in the body."""
    problems = []
    for path in files:
        where = path.relative_to(root)
        if FRENCH_LETTERS.search(path.name):
            problems.append(f"{where}: file name with French letters")
        for heading in headings(path):
            if FRENCH_LETTERS.search(heading):
                problems.append(f"{where}: French heading '{heading}'")
    return problems


def check(root: Path = ROOT) -> list[str]:
    files = markdown_files(root)
    return (
        check_links(root, files)
        + check_adrs(root)
        + check_designs(root)
        + check_orphans(root)
        + check_language(root, files)
    )


def main() -> int:
    problems = check()
    for problem in problems:
        print(problem)
    print(f"{len(problems)} problem(s) in {len(markdown_files(ROOT))} documents")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
