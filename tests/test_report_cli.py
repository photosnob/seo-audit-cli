from seoaudit.cli import main
from seoaudit.html_report import render_html
from seoaudit.models import Issue
from seoaudit.report import render_json, write_report
from tests.fixture_site import FixtureServer, build_clean_app, build_demo_app, build_external_app
from tests.helpers import bare_report, make_page


def test_html_escapes_untrusted_text(tmp_path) -> None:  # type: ignore[no-untyped-def]
    page = make_page(title="<script>alert(1)</script>")
    issues = [Issue("high", "title_missing", page.url, "<img src=x onerror=alert(1)>")]
    report = bare_report([page], issues)
    text = render_html(report)
    assert "<script>alert(1)" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<img src=x" not in text
    payload = render_json(report)
    assert payload.strip().startswith("{")
    paths = write_report(report, tmp_path)
    assert (
        paths["issues"].read_text(encoding="utf-8").splitlines()[0] == "severity,code,url,message"
    )
    assert "title_missing" in paths["issues"].read_text(encoding="utf-8")


def test_cli_writes_a_report_and_honors_fail_on(tmp_path) -> None:  # type: ignore[no-untyped-def]
    clean = FixtureServer(build_clean_app())
    external = FixtureServer(build_external_app())
    demo = FixtureServer(build_demo_app(external.origin))
    try:
        clean_dir = tmp_path / "clean"
        demo_dir = tmp_path / "demo"
        clean_code = main(
            [
                "crawl",
                clean.origin + "/",
                "--output-dir",
                str(clean_dir),
                "--rate-limit",
                "200",
                "--max-pages",
                "10",
                "--fail-on",
                "critical",
                "--no-trust-env",
                "--quiet",
            ]
        )
        demo_code = main(
            [
                "crawl",
                demo.origin + "/",
                "--output-dir",
                str(demo_dir),
                "--rate-limit",
                "200",
                "--max-pages",
                "200",
                "--fail-on",
                "critical",
                "--no-trust-env",
                "--quiet",
            ]
        )
    finally:
        clean.close()
        demo.close()
        external.close()
    assert clean_code == 0
    assert (clean_dir / "report.html").exists()
    assert (clean_dir / "report.json").exists()
    assert demo_code == 1
    assert (demo_dir / "issues.csv").exists()
    assert main(["crawl", "http://"]) == 2
