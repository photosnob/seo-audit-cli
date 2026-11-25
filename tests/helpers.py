"""Shared constructors for unit tests."""

from dataclasses import asdict

from seoaudit.models import (
    SEVERITIES,
    AuditReport,
    ExternalCheck,
    Hop,
    Issue,
    JsonLdBlock,
    Page,
    Score,
    empty_page,
)
from seoaudit.score import score_issues
from seoaudit.thresholds import Thresholds

GOOD_TITLE = "A perfectly fine title for this page"
GOOD_META = (
    "A useful description of this page that sits comfortably inside the usual snippet range."
)


def make_page(url: str = "https://example.com/page", **overrides: object) -> Page:
    if not 30 <= len(GOOD_TITLE) <= 60:
        raise RuntimeError(len(GOOD_TITLE))
    if not 70 <= len(GOOD_META) <= 160:
        raise RuntimeError(len(GOOD_META))
    page = empty_page(url)
    page.final_url = url
    page.status = 200
    page.parsed = True
    page.is_html = True
    page.content_type = "text/html; charset=utf-8"
    page.title = GOOD_TITLE
    page.meta_description = GOOD_META
    page.h1s = ["A real heading"]
    page.canonicals = [url]
    page.jsonld = [JsonLdBlock(True, None, ["WebPage"], False)]
    page.og = {
        "og:title": GOOD_TITLE,
        "og:description": GOOD_META,
        "og:image": "https://example.com/og.png",
    }
    page.word_count = 400
    page.depth = 0
    page.hops = [Hop(url, 200)]
    page.html_bytes = 12000
    for key, value in overrides.items():
        setattr(page, key, value)
    return page


def bare_report(pages: list[Page], issues: list[Issue] | None = None) -> AuditReport:
    found = issues or []
    return AuditReport(
        version="0.1.0",
        start_url=pages[0].url if pages else "https://example.com/",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        duration_seconds=1.0,
        settings={"thresholds": asdict(Thresholds())},
        robots_status=200,
        robots_found=True,
        robots_unavailable=False,
        robots_error=None,
        robots_text="User-agent: *\nDisallow:\n",
        robots_sitemaps=[],
        crawl_delay=None,
        sitemap_sources=["https://example.com/sitemap.xml"],
        sitemap_urls=[page.final_url for page in pages],
        sitemap_errors=[],
        sitemap_truncated=False,
        pages=pages,
        external=[],
        external_considered=0,
        blocked_urls=[],
        requests_made=len(pages),
        issues=found,
        score=score_issues(found, has_pages=bool(pages)),
    )


def codes(issues: list[Issue]) -> set[str]:
    return {issue.code for issue in issues}


assert set(SEVERITIES) == {"critical", "high", "medium", "low", "info"}
_ = ExternalCheck
_ = Score
