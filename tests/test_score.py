from seoaudit.models import Issue
from seoaudit.score import score_issues


def test_weights_and_cap() -> None:
    one = score_issues(
        [Issue("critical", "redirect_loop", "https://example.com/a", "loop")],
        has_pages=True,
    )
    assert one.overall == 85.0

    many = [
        Issue("high", "title_missing", f"https://example.com/{index}", "missing")
        for index in range(10)
    ]
    capped = score_issues(many, has_pages=True)
    assert capped.deductions[0].count == 10
    assert capped.deductions[0].points == 24.0
    assert capped.overall == 76.0
    assert capped.categories["metadata"] == 76.0
    assert capped.categories["crawl"] == 100.0


def test_info_and_empty_crawl() -> None:
    info = score_issues(
        [Issue("info", "jsonld_missing", "https://example.com/", "none")],
        has_pages=True,
    )
    assert info.overall == 100.0
    assert score_issues([], has_pages=False).overall is None
    flooded = score_issues(
        [Issue("critical", "redirect_loop", f"https://example.com/{i}", "loop") for i in range(20)],
        has_pages=True,
    )
    assert flooded.overall == 55.0
    assert flooded.overall is not None and flooded.overall >= 0
