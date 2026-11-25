from seoaudit.checks import collect_issues
from seoaudit.models import ExternalCheck, Hop, HreflangRef, Issue, JsonLdBlock
from seoaudit.thresholds import Thresholds
from tests.helpers import codes, make_page


def _issues(pages: list, **kwargs: object) -> list[Issue]:
    start = kwargs.pop("start_url", pages[0].final_url if pages else "https://example.com/")
    return collect_issues(pages, start_url=str(start), **kwargs)  # type: ignore[arg-type]


def test_clean_page_scores_clean() -> None:
    page = make_page()
    found = _issues(
        [page], sitemap_urls=[page.url], sitemap_sources=["https://example.com/sitemap.xml"]
    )
    assert found == []


def test_title_meta_and_h1_boundaries() -> None:
    short = make_page(title="Notes")
    exact = make_page(title="x" * 30)
    long = make_page(title="y" * 61)
    assert "title_too_short" in codes(
        _issues([short], sitemap_sources=["x"], sitemap_urls=[short.url])
    )
    assert "title_too_short" not in codes(
        _issues([exact], sitemap_sources=["x"], sitemap_urls=[exact.url])
    )
    assert "title_too_long" in codes(
        _issues([long], sitemap_sources=["x"], sitemap_urls=[long.url])
    )
    missing_meta = make_page(meta_description=None)
    assert "meta_description_missing" in codes(
        _issues([missing_meta], sitemap_sources=["x"], sitemap_urls=[missing_meta.url])
    )
    short_meta = make_page(meta_description="Too short.")
    assert "meta_description_too_short" in codes(
        _issues([short_meta], sitemap_sources=["x"], sitemap_urls=[short_meta.url])
    )
    assert "h1_missing" in codes(
        _issues(
            [make_page(h1s=[])], sitemap_sources=["x"], sitemap_urls=["https://example.com/page"]
        )
    )
    assert "h1_multiple" in codes(
        _issues(
            [make_page(h1s=["One", "Two"])],
            sitemap_sources=["x"],
            sitemap_urls=["https://example.com/page"],
        )
    )
    assert codes(
        _issues(
            [make_page(h1s=[], h1_empty=1)],
            sitemap_sources=["x"],
            sitemap_urls=["https://example.com/page"],
        )
    ) >= {"h1_empty"}
    assert "h1_missing" not in codes(
        _issues(
            [make_page(h1s=[], h1_empty=1)],
            sitemap_sources=["x"],
            sitemap_urls=["https://example.com/page"],
        )
    )


def test_duplicates_are_case_insensitive() -> None:
    first_meta = "A unique description for the first page in the duplicate-title unit test case."
    second_meta = "A unique description for the second page in the duplicate-title unit test case."
    first = make_page(
        "https://example.com/a",
        title="Same Title Here For Both Pages",
        meta_description=first_meta,
    )
    second = make_page(
        "https://example.com/b",
        title="  same   title here for both pages",
        meta_description=second_meta,
    )
    found = _issues([first, second], sitemap_sources=["x"], sitemap_urls=[first.url, second.url])
    assert codes(found) == {"title_duplicate"}


def test_canonical_robots_and_hreflang() -> None:
    page = make_page(canonicals=[])
    assert "canonical_missing" in codes(
        _issues([page], sitemap_sources=["x"], sitemap_urls=[page.url])
    )
    conflict = make_page(canonicals=["https://example.com/page", "https://example.com/other"])
    assert "canonical_multiple" in codes(
        _issues([conflict], sitemap_sources=["x"], sitemap_urls=[conflict.url])
    )
    other = make_page("https://example.com/other", status=404, parsed=False)
    bad = make_page(canonicals=["https://example.com/other"])
    found = _issues([bad, other], sitemap_sources=["x"], sitemap_urls=[bad.url, other.url])
    assert {"canonical_non_self", "canonical_target_error"} <= codes(found)
    noindex = make_page(robots="noindex, nofollow")
    assert {"noindex", "nofollow"} <= codes(
        _issues([noindex], sitemap_sources=["x"], sitemap_urls=[noindex.url])
    )
    source = make_page(
        hreflang=[
            HreflangRef("english", "/x", "https://example.com/elsewhere", False),
            HreflangRef("de", "https://example.com/missing", "https://example.com/missing", True),
        ]
    )
    found = _issues([source], sitemap_sources=["x"], sitemap_urls=[source.url])
    assert {
        "hreflang_invalid",
        "hreflang_not_absolute",
        "hreflang_missing_self",
        "hreflang_target_not_crawled",
    } <= codes(found)


def test_links_content_and_sitemap_gaps() -> None:
    target = make_page(
        "https://example.com/missing",
        status=404,
        parsed=False,
        hops=[Hop("https://example.com/missing", 404)],
    )
    source = make_page(
        internal_links=["https://example.com/missing"], external_links=["https://other.example/x"]
    )
    external = [ExternalCheck("https://other.example/x", 404, None, "https://other.example/x")]
    found = _issues(
        [source, target],
        sitemap_sources=["https://example.com/sitemap.xml"],
        sitemap_urls=["https://example.com/page", "https://example.com/extra"],
        external=external,
    )
    assert {"broken_internal_link", "broken_external_link", "sitemap_url_not_crawled"} <= codes(
        found
    )
    thin = make_page(word_count=80, depth=4)
    very = make_page("https://example.com/tiny", word_count=10)
    sized = make_page("https://example.com/big", html_bytes=250_000)
    found = _issues(
        [thin, very, sized],
        sitemap_sources=["x"],
        sitemap_urls=[thin.url, very.url, sized.url],
    )
    assert {"thin_content", "very_thin_content", "deep_page", "html_large"} <= codes(found)
    huge = make_page(html_bytes=600_000, word_count=10)
    found = _issues([huge], sitemap_sources=["x"], sitemap_urls=[huge.url], thresholds=Thresholds())
    assert "html_very_large" in codes(found)
    assert "very_thin_content" in codes(found)
    assert "html_large" not in codes(found)
    assert "thin_content" not in codes(found)


def test_fetch_and_sitemap_site_issues() -> None:
    failed = make_page(status=None, parsed=False, error="timed out", hops=[])
    loop = make_page(
        url="https://example.com/a",
        final_url="https://example.com/a",
        status=301,
        parsed=False,
        loop=True,
        hops=[Hop("https://example.com/a", 301), Hop("https://example.com/b", 301)],
    )
    chain = make_page(
        url="https://example.com/old",
        final_url="https://example.com/new",
        status=200,
        parsed=False,
        hops=[
            Hop("https://example.com/old", 301),
            Hop("https://example.com/mid", 302),
            Hop("https://example.com/new", 200),
        ],
    )
    found = _issues([failed, loop, chain], sitemap_sources=[], sitemap_urls=[])
    assert {"fetch_failed", "redirect_loop", "redirect_chain", "sitemap_missing"} <= codes(found)
    blocked = _issues(
        [make_page()],
        sitemap_sources=["x"],
        sitemap_urls=[make_page().url],
        blocked_urls=["https://example.com/private"],
        blocked_referrers={"https://example.com/private": "https://example.com/page"},
    )
    assert any(
        issue.code == "blocked_by_robots" and "https://example.com/page" in issue.message
        for issue in blocked
    )
    empty = make_page(jsonld=[JsonLdBlock(True, None, [], True)])
    invalid = make_page(
        "https://example.com/bad",
        jsonld=[JsonLdBlock(False, "Invalid JSON (Expecting value)", [], False)],
    )
    assert {"jsonld_empty", "jsonld_invalid"} <= codes(
        _issues([empty, invalid], sitemap_sources=["x"], sitemap_urls=[empty.url, invalid.url])
    )
