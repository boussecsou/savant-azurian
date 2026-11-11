"""Turn a Markdown guide into a PDF: Markdown to HTML (images embedded), then Chromium's print to PDF.

    uv run --with markdown python -m scripts.build_pdf docs/user-guide.md docs/user-guide.pdf

The `markdown` package is only needed here, so it is not a project dependency. Chromium or Chrome is
found on the PATH or in a Playwright cache; pass --chrome to choose one.
"""

from __future__ import annotations

import argparse
import base64
import html
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font: 11pt/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #1f2328; }
h1 { font-size: 24pt; border-bottom: 2px solid #5b5bd6; padding-bottom: 6pt; }
h2 { font-size: 16pt; margin-top: 22pt; border-bottom: 1px solid #d0d7de; padding-bottom: 3pt; page-break-after: avoid; }
h3 { font-size: 13pt; page-break-after: avoid; }
img { max-width: 100%; border: 1px solid #d0d7de; border-radius: 6px; page-break-inside: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; page-break-inside: avoid; }
th, td { border: 1px solid #d0d7de; padding: 4pt 7pt; text-align: left; vertical-align: top; }
th { background: #f6f8fa; }
code { font: 9.5pt ui-monospace, SFMono-Regular, Consolas, monospace; background: #f6f8fa; padding: 1pt 3pt; border-radius: 3px; }
pre { background: #f6f8fa; padding: 8pt; border-radius: 6px; overflow-wrap: anywhere; white-space: pre-wrap; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { margin: 8pt 0; padding: 2pt 10pt; border-left: 3px solid #5b5bd6; color: #57606a; }
a { color: #0969da; text-decoration: none; }
"""


def find_chrome(explicit: str | None) -> str:
    if explicit:
        return explicit
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        if found := shutil.which(name):
            return found
    cache = Path.home() / ".cache" / "ms-playwright"
    candidates = sorted(cache.glob("chromium-*/chrome-linux64/chrome")) if cache.exists() else []
    if candidates:
        return str(candidates[-1])
    raise SystemExit("Chromium not found: install it or pass --chrome <path>.")


def embed_images(markup: str, base: Path) -> str:
    """Replace local image sources with data URIs so the HTML file is self-contained."""

    def replace(match: re.Match[str]) -> str:
        source = match.group(2)
        if source.startswith(("http://", "https://", "data:")):
            return match.group(0)
        path = (base / source).resolve()
        if not path.exists():
            return match.group(0)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = base64.b64encode(path.read_bytes()).decode()
        return f'{match.group(1)}data:{mime};base64,{data}"'

    return re.sub(r'(<img [^>]*src=")([^"]+)"', replace, markup)


def render(markdown_path: Path) -> str:
    try:
        import markdown
    except ImportError as error:  # pragma: no cover - guidance for the person running it
        raise SystemExit(
            "Run with the package available: uv run --with markdown python -m scripts.build_pdf …"
        ) from error
    source = markdown_path.read_text(encoding="utf-8")
    body = markdown.markdown(source, extensions=["tables", "fenced_code", "sane_lists"])
    # Links to other Markdown pages are meaningless on paper: keep the text, drop the link.
    body = re.sub(r'<a href="(?!https?:|#|mailto:)[^"]*">(.*?)</a>', r"\1", body)
    title = html.escape(source.splitlines()[0].lstrip("# ").strip())
    page = f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>"
    return embed_images(page, markdown_path.parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("markdown", type=Path)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--chrome")
    args = parser.parse_args()

    chrome = find_chrome(args.chrome)
    with tempfile.TemporaryDirectory() as folder:
        page = Path(folder) / "guide.html"
        page.write_text(render(args.markdown), encoding="utf-8")
        profile = Path(folder) / "profile"
        subprocess.run(  # noqa: S603 - fixed arguments, a local file
            [
                chrome,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--user-data-dir={profile}",
                f"--print-to-pdf={args.pdf.resolve()}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    print(f"Written: {args.pdf} ({args.pdf.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
