"""The documentation checker: it passes on the repository and catches each kind of mistake."""

from pathlib import Path

from scripts import check_docs

ADR = """# ADR-0001: A decision

- **Status:** Accepted
- **Date:** 2026-01-01
- **Tags:** infra

## Context

Text.
"""
INDEX = "| ADR | Decision | Status |\n| --- | --- | --- |\n| [0001](0001-a-decision.md) | A decision | Accepted |\n"


def tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


def test_the_repository_documentation_is_clean():
    assert check_docs.check() == []


def test_a_broken_link_and_a_missing_anchor_are_reported(tmp_path):
    root = tree(tmp_path, {"README.md": "[x](missing.md) [y](docs/a.md#nope)\n", "docs/a.md": "# Title\n"})
    problems = check_docs.check_links(root, check_docs.markdown_files(root))
    assert any("broken link missing.md" in p for p in problems)
    assert any("no heading for the anchor docs/a.md#nope" in p for p in problems)


def test_links_inside_code_are_not_links(tmp_path):
    root = tree(tmp_path, {"README.md": "Use `[x](missing.md)`.\n\n```\n[y](missing.md)\n```\n"})
    assert check_docs.check_links(root, check_docs.markdown_files(root)) == []


def test_anchors_follow_github_slugs(tmp_path):
    root = tree(
        tmp_path, {"README.md": "[a](docs/a.md#9-turn-it-on-portal)\n", "docs/a.md": "### 9. Turn it on (portal)\n"}
    )
    assert check_docs.check_links(root, check_docs.markdown_files(root)) == []


def test_a_well_formed_adr_passes(tmp_path):
    root = tree(tmp_path, {"docs/adr/README.md": INDEX, "docs/adr/0001-a-decision.md": ADR})
    assert check_docs.check_adrs(root) == []


def test_an_adr_with_a_bad_status_or_missing_from_the_index_is_reported(tmp_path):
    bad = ADR.replace("Accepted", "Maybe")
    root = tree(tmp_path, {"docs/adr/README.md": "no table\n", "docs/adr/0001-a-decision.md": bad})
    problems = check_docs.check_adrs(root)
    assert any("status must start with" in p for p in problems)
    assert any("missing from the index" in p for p in problems)


def test_an_orphan_document_is_reported(tmp_path):
    root = tree(tmp_path, {"docs/README.md": "# Docs\n", "docs/lonely.md": "# Lonely\n"})
    assert any("lonely.md" in p for p in check_docs.check_orphans(root))


def test_french_headings_are_reported_but_french_body_text_is_not(tmp_path):
    root = tree(tmp_path, {"README.md": "# Titre créé\n\nUne phrase en français : « Je cherche ça. »\n"})
    problems = check_docs.check_language(root, check_docs.markdown_files(root))
    assert problems == ["README.md: French heading 'Titre créé'"]
