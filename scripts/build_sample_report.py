"""Regenerate examples/sample-report from the local fixture servers.

The numbers in the README are copied from this output. They describe the
fixture site in tests/fixture_site.py, not a live website.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from seoaudit.cli import main  # noqa: E402
from tests.fixture_site import FixtureServer, build_clean_app, build_demo_app, build_external_app  # noqa: E402


def main_script() -> None:
    destination = ROOT / "examples" / "sample-report"
    if destination.exists():
        shutil.rmtree(destination)
    external = FixtureServer(build_external_app(), 8766)
    demo = FixtureServer(build_demo_app(external.origin), 8765)
    clean = FixtureServer(build_clean_app(), 8767)
    try:
        demo_code = main(
            [
                "crawl",
                demo.origin + "/",
                "--output-dir",
                str(destination / "fixture-site"),
                "--max-pages",
                "200",
                "--rate-limit",
                "200",
                "--no-trust-env",
            ]
        )
        print("---")
        clean_code = main(
            [
                "crawl",
                clean.origin + "/",
                "--output-dir",
                str(destination / "clean-site"),
                "--max-pages",
                "10",
                "--rate-limit",
                "200",
                "--no-trust-env",
            ]
        )
    finally:
        demo.close()
        external.close()
        clean.close()
    if demo_code not in {0, 1} or clean_code != 0:
        raise SystemExit(f"unexpected exit codes demo={demo_code} clean={clean_code}")


if __name__ == "__main__":
    main_script()
