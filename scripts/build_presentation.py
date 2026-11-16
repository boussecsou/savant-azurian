"""Print the project presentation (docs/presentation/presentation[.fr].html) to a PDF with headless Chromium.

    uv run python -m scripts.build_presentation [--lang en|fr] [--output PATH]

The page is 16:9 (1280 x 720 px) so that it reads well as a LinkedIn document. Fonts are bundled next to
the HTML; Chromium or Chrome is found as in `scripts.build_pdf`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.build_pdf import find_chrome

SOURCES = {
    "en": (Path("docs/presentation/presentation.html"), Path("docs/savant-azurian-presentation.pdf")),
    "fr": (Path("docs/presentation/presentation.fr.html"), Path("docs/savant-azurian-presentation.fr.pdf")),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lang", choices=sorted(SOURCES), default="en")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--chrome")
    args = parser.parse_args()

    source, default_output = SOURCES[args.lang]
    output = args.output or default_output
    chrome = find_chrome(args.chrome)
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(  # noqa: S603 - fixed arguments, a local file
            [
                chrome,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--no-pdf-header-footer",
                "--virtual-time-budget=5000",
                f"--user-data-dir={Path(folder) / 'profile'}",
                f"--print-to-pdf={output.resolve()}",
                source.resolve().as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    print(f"Written: {output} ({output.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
