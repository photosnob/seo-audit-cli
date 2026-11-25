import asyncio

from seoaudit.crawler import RateLimiter, run_audit
from seoaudit.models import AuditConfig
from seoaudit.report import write_report
from tests.fixture_site import (
    FixtureServer,
    build_bad_sitemap_app,
    build_clean_app,
    build_demo_app,
    build_external_app,
    build_robots_down_app,
    build_slow_app,
)


def _audit(origin: str, **overrides: object) -> object:
    params: dict[str, object] = {
        "start_url": origin + "/",
        "max_pages": 200,
        "rate_limit": 200,
        "concurrency": 4,
        "timeout": 5,
        "trust_env": False,
    }
    params.update(overrides)
    config = AuditConfig(**params)  # type: ignore[arg-type]
    return asyncio.run(run_audit(config))


def _codes(report: object, suffix: str | None = None) -> set[str]:
    issues = report.issues  # type: ignore[attr-defined]
    if suffix is None:
        return {issue.code for issue in issues}
    return {issue.code for issue in issues if str(issue.url).endswith(suffix)}


def test_clean_site_scores_100() -> None:
    server = FixtureServer(build_clean_app())
    try:
        report = _audit(server.origin)
    finally:
        server.close()
    assert report.score.overall == 100.0  # type: ignore[attr-defined]
    assert report.issues == []  # type: ignore[attr-defined]
    assert report.pages[0].word_count >= 300  # type: ignore[attr-defined]
    assert report.robots_found is True  # type: ignore[attr-defined]


def test_demo_site_finds_the_planted_faults(tmp_path) -> None:  # type: ignore[no-untyped-def]
    external = FixtureServer(build_external_app())
    server = FixtureServer(build_demo_app(external.origin))
    try:
        report = _audit(server.origin)
        paths = write_report(report, tmp_path)  # type: ignore[arg-type]
    finally:
        server.close()
        external.close()
    found = _codes(report)
    expected = {
        "title_too_short",
        "title_too_long",
        "title_missing",
        "title_duplicate",
        "meta_description_missing",
        "meta_description_too_short",
        "meta_description_too_long",
        "meta_description_duplicate",
        "h1_missing",
        "h1_multiple",
        "h1_empty",
        "canonical_missing",
        "canonical_multiple",
        "canonical_non_self",
        "canonical_target_error",
        "noindex",
        "nofollow",
        "hreflang_invalid",
        "hreflang_not_absolute",
        "hreflang_missing_self",
        "hreflang_no_return",
        "hreflang_target_error",
        "http_client_error",
        "http_server_error",
        "rate_limited",
        "redirect_chain",
        "redirect_loop",
        "redirect_missing_location",
        "redirect_offsite",
        "too_many_redirects",
        "broken_internal_link",
        "broken_external_link",
        "blocked_by_robots",
        "orphan_page",
        "sitemap_url_non_200",
        "sitemap_url_redirect",
        "sitemap_url_noindex",
        "jsonld_invalid",
        "jsonld_empty",
        "jsonld_missing",
        "og_incomplete",
        "img_alt_missing",
        "img_alt_empty",
        "html_very_large",
        "deep_page",
        "very_thin_content",
        "thin_content",
    }
    missing = expected - found
    assert not missing, missing
    assert _codes(report, "/sitemap-only") == set()
    assert _codes(report, "/about") == {"thin_content"}
    assert _codes(report, "/orphan") == {"orphan_page"}
    assert _codes(report, "/guides/deep") == {"deep_page"}
    deep = next(page for page in report.pages if page.url.endswith("/guides/deep"))  # type: ignore[attr-defined]
    assert deep.depth == 4
    assert not any("/private" in page.url for page in report.pages)  # type: ignore[attr-defined]
    assert any(url.endswith("/private/secret") for url in report.blocked_urls)  # type: ignore[attr-defined]
    assert report.score.overall is not None  # type: ignore[attr-defined]
    assert 0 <= report.score.overall <= 100  # type: ignore[attr-defined]
    html = paths["html"].read_text(encoding="utf-8")
    assert "noindex" in html
    assert f"{report.score.overall:.1f}" in html  # type: ignore[attr-defined]
    assert "Health score" in html


def test_max_pages_leaves_sitemap_urls() -> None:
    external = FixtureServer(build_external_app())
    server = FixtureServer(build_demo_app(external.origin))
    try:
        report = _audit(server.origin, max_pages=1, check_external=False)
    finally:
        server.close()
        external.close()
    assert len(report.pages) == 1  # type: ignore[attr-defined]
    assert "sitemap_url_not_crawled" in _codes(report)


def test_ignore_robots_fetches_private() -> None:
    external = FixtureServer(build_external_app())
    server = FixtureServer(build_demo_app(external.origin))
    try:
        report = _audit(server.origin, respect_robots=False, check_external=False)
    finally:
        server.close()
        external.close()
    assert any(page.url.endswith("/private/secret") for page in report.pages)  # type: ignore[attr-defined]


def test_robots_and_sitemap_failures() -> None:
    down = FixtureServer(build_robots_down_app())
    bad = FixtureServer(build_bad_sitemap_app())
    try:
        robots = _audit(down.origin, check_external=False)
        sitemap = _audit(bad.origin, check_external=False)
    finally:
        down.close()
        bad.close()
    assert "robots_unavailable" in _codes(robots)
    assert robots.pages  # type: ignore[attr-defined]
    assert "sitemap_invalid" in _codes(sitemap)


def test_timeout_is_a_fetch_failure() -> None:
    server = FixtureServer(build_slow_app())
    try:
        report = _audit(server.origin, timeout=0.2, max_pages=1, check_external=False)
    finally:
        server.close()
    assert "fetch_failed" in _codes(report)


def test_rate_limiter_spaces_requests() -> None:
    async def run() -> float:
        limiter = RateLimiter(20)
        loop = asyncio.get_running_loop()
        started = loop.time()
        for _ in range(4):
            await limiter.acquire()
        return loop.time() - started

    elapsed = asyncio.run(run())
    assert elapsed >= 0.12
    assert RateLimiter(100, crawl_delay=0.5).interval == 0.5
