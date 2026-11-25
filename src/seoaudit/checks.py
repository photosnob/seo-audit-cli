"""Turn a finished crawl into a prioritized issue list.

Content checks run once per final HTML document. A URL that only redirects
keeps its redirect findings and does not repeat the destination's title,
H1, and word-count findings.
"""

import re
from collections import defaultdict
from collections.abc import Callable

from seoaudit.catalog import require_check
from seoaudit.models import SEVERITIES, AuditReport, ExternalCheck, Issue, Page, Severity
from seoaudit.parse import valid_hreflang
from seoaudit.sitemap import SitemapProblem
from seoaudit.thresholds import Thresholds
from seoaudit.urls import dedupe

_SEVERITY_RANK = {name: index for index, name in enumerate(SEVERITIES)}


def collect_issues(
    pages: list[Page],
    *,
    start_url: str,
    sitemap_urls: list[str] | None = None,
    sitemap_sources: list[str] | None = None,
    sitemap_problems: list[SitemapProblem] | None = None,
    sitemap_truncated: bool = False,
    robots_unavailable: bool = False,
    robots_error: str | None = None,
    external: list[ExternalCheck] | None = None,
    blocked_urls: list[str] | None = None,
    blocked_referrers: dict[str, str] | None = None,
    thresholds: Thresholds | None = None,
) -> list[Issue]:
    limits = thresholds or Thresholds()
    documents = iter_documents(pages)
    external_list = external or []
    external_by_url = {item.url: item for item in external_list}
    blocked = blocked_urls or []
    referrers = blocked_referrers or {}
    issues: list[Issue] = []
    issues.extend(
        _site_issues(
            start_url,
            sitemap_sources or [],
            sitemap_problems or [],
            sitemap_truncated,
            robots_unavailable,
            robots_error,
        )
    )
    for page in pages:
        issues.extend(_fetch_issues(page))
    for document in documents:
        issues.extend(_on_page_issues(document, pages, external_by_url, limits))
    issues.extend(_duplicate_issues(documents))
    issues.extend(_link_issues(documents, pages, external_list))
    issues.extend(_sitemap_issues(pages, documents, sitemap_urls or [], blocked))
    for url in blocked:
        referrer = referrers.get(url)
        extra = f" First seen from {referrer}." if referrer else ""
        issues.append(
            _issue(
                "info",
                "blocked_by_robots",
                url,
                f"Disallowed by robots.txt and not fetched.{extra}",
            )
        )
    return sort_issues(_dedupe(issues))


def iter_documents(pages: list[Page]) -> list[Page]:
    groups: dict[str, list[Page]] = defaultdict(list)
    for page in pages:
        if page.parsed:
            groups[page.final_url].append(page)
    preferred: dict[str, Page] = {}
    for final, group in groups.items():
        preferred[final] = next((page for page in group if page.url == final), group[0])
    ordered: list[Page] = []
    seen: set[str] = set()
    for page in pages:
        if page.parsed and page.final_url not in seen:
            ordered.append(preferred[page.final_url])
            seen.add(page.final_url)
    return ordered


def sort_issues(issues: list[Issue]) -> list[Issue]:
    return sorted(
        issues,
        key=lambda issue: (_SEVERITY_RANK[issue.severity], issue.code, issue.url, issue.message),
    )


def _site_issues(
    start_url: str,
    sitemap_sources: list[str],
    sitemap_problems: list[SitemapProblem],
    sitemap_truncated: bool,
    robots_unavailable: bool,
    robots_error: str | None,
) -> list[Issue]:
    issues: list[Issue] = []
    if robots_unavailable:
        detail = robots_error or "robots.txt could not be used."
        issues.append(_issue("medium", "robots_unavailable", start_url, detail))
    if not sitemap_sources and not sitemap_problems:
        issues.append(
            _issue(
                "medium",
                "sitemap_missing",
                start_url,
                "No sitemap was found in robots.txt, /sitemap.xml, or /sitemap_index.xml.",
            )
        )
    for problem in sitemap_problems:
        issues.append(_issue("high", problem.code, problem.url, problem.message))
    if sitemap_truncated:
        issues.append(
            _issue(
                "info",
                "sitemap_truncated",
                start_url,
                "Sitemap parsing stopped at the URL or child-sitemap cap.",
            )
        )
    return issues


def _fetch_issues(page: Page) -> list[Issue]:
    issues: list[Issue] = []
    if page.loop:
        urls = [hop.url for hop in page.hops]
        if page.final_url and (not urls or urls[-1] != page.final_url):
            urls.append(page.final_url)
        issues.append(
            _issue("critical", "redirect_loop", page.url, "Redirect loop: " + " -> ".join(urls))
        )
        return issues
    if page.too_many_redirects:
        path = " -> ".join(hop.url for hop in page.hops)
        issues.append(
            _issue(
                "high",
                "too_many_redirects",
                page.url,
                f"Stopped after {len(page.hops) - 1} redirects: {path}",
            )
        )
        return issues
    if page.missing_location:
        issues.append(
            _issue(
                "medium",
                "redirect_missing_location",
                page.url,
                "A redirect response had no usable Location header.",
            )
        )
        return issues
    if page.error and page.status is None:
        issues.append(_issue("high", "fetch_failed", page.url, f"Fetch failed: {page.error}"))
        return issues
    if page.status == 429:
        issues.append(
            _issue("high", "rate_limited", page.url, "Server returned 429 Too Many Requests.")
        )
    elif page.status is not None and page.status >= 500:
        issues.append(_issue("critical", "http_server_error", page.url, _status_message(page)))
    elif page.status is not None and page.status >= 400:
        issues.append(_issue("high", "http_client_error", page.url, _status_message(page)))
    redirects = _redirect_count(page)
    if page.offsite_redirect:
        issues.append(
            _issue(
                "medium", "redirect_offsite", page.url, f"Redirects off site to {page.final_url}."
            )
        )
    if redirects >= 3:
        issues.append(_issue("high", "redirect_chain", page.url, _chain_message(page, redirects)))
    elif redirects == 2:
        issues.append(_issue("medium", "redirect_chain", page.url, _chain_message(page, redirects)))
    if page.truncated:
        issues.append(
            _issue(
                "medium",
                "response_truncated",
                page.final_url,
                f"HTML download stopped at the byte limit. {page.html_bytes} bytes were accounted for.",
            )
        )
    return issues


def _on_page_issues(
    page: Page,
    pages: list[Page],
    external_by_url: dict[str, ExternalCheck],
    limits: Thresholds,
) -> list[Issue]:
    issues: list[Issue] = []
    issues.extend(_title_issues(page, limits))
    issues.extend(_meta_issues(page, limits))
    issues.extend(_h1_issues(page))
    issues.extend(_canonical_issues(page, pages, external_by_url))
    issues.extend(_robots_directive_issues(page))
    issues.extend(_hreflang_issues(page, pages))
    issues.extend(_structured_data_issues(page))
    issues.extend(_social_issues(page))
    issues.extend(_image_issues(page))
    issues.extend(_size_issues(page, limits))
    issues.extend(_content_issues(page, limits))
    return issues


def _title_issues(page: Page, limits: Thresholds) -> list[Issue]:
    title = page.title
    if not title:
        return [
            _issue("high", "title_missing", page.final_url, "This HTML document has no <title>.")
        ]
    length = len(title)
    if length < limits.title_min:
        return [
            _issue(
                "low",
                "title_too_short",
                page.final_url,
                f'Title is {length} characters ("{_clip(title)}"). The usual range is {limits.title_min}-{limits.title_max}.',
            )
        ]
    if length > limits.title_max:
        return [
            _issue(
                "low",
                "title_too_long",
                page.final_url,
                f'Title is {length} characters ("{_clip(title)}"). The usual range is {limits.title_min}-{limits.title_max}.',
            )
        ]
    return []


def _meta_issues(page: Page, limits: Thresholds) -> list[Issue]:
    meta = page.meta_description
    if not meta:
        return [
            _issue(
                "medium",
                "meta_description_missing",
                page.final_url,
                "This HTML document has no meta description.",
            )
        ]
    length = len(meta)
    if length < limits.meta_min:
        return [
            _issue(
                "low",
                "meta_description_too_short",
                page.final_url,
                f"Meta description is {length} characters. The usual range is {limits.meta_min}-{limits.meta_max}.",
            )
        ]
    if length > limits.meta_max:
        return [
            _issue(
                "low",
                "meta_description_too_long",
                page.final_url,
                f"Meta description is {length} characters. The usual range is {limits.meta_min}-{limits.meta_max}.",
            )
        ]
    return []


def _h1_issues(page: Page) -> list[Issue]:
    issues: list[Issue] = []
    if page.h1_empty:
        issues.append(
            _issue("medium", "h1_empty", page.final_url, f"{page.h1_empty} empty H1 element(s).")
        )
    if not page.h1s and page.h1_empty:
        return issues
    if not page.h1s:
        issues.append(_issue("high", "h1_missing", page.final_url, "This HTML document has no H1."))
    elif len(page.h1s) > 1:
        shown = "; ".join(_clip(item, 80) for item in page.h1s[:3])
        issues.append(
            _issue(
                "medium", "h1_multiple", page.final_url, f"{len(page.h1s)} H1 elements: {shown}."
            )
        )
    return issues


def _canonical_issues(
    page: Page,
    pages: list[Page],
    external_by_url: dict[str, ExternalCheck],
) -> list[Issue]:
    url = page.final_url
    canonicals = dedupe(page.canonicals)
    issues: list[Issue] = []
    if not canonicals:
        issues.append(
            _issue("medium", "canonical_missing", url, "No canonical link element or Link header.")
        )
    elif len(canonicals) > 1:
        shown = ", ".join(canonicals[:3])
        extra = f" and {len(canonicals) - 3} more" if len(canonicals) > 3 else ""
        issues.append(
            _issue("high", "canonical_multiple", url, f"Canonical URLs disagree: {shown}{extra}.")
        )
    elif canonicals[0] != url:
        issues.append(
            _issue("medium", "canonical_non_self", url, f"Canonical points to {canonicals[0]}.")
        )
    for canonical in canonicals:
        status = _lookup_status(canonical, pages, external_by_url)
        if status is not None and status >= 400:
            issues.append(
                _issue(
                    "high",
                    "canonical_target_error",
                    url,
                    f"Canonical {canonical} returned {status}.",
                )
            )
    return issues


def _robots_directive_issues(page: Page) -> list[Issue]:
    robots = (page.robots or "").lower()
    issues: list[Issue] = []
    if "noindex" in robots:
        issues.append(
            _issue("medium", "noindex", page.final_url, f"noindex is set ({page.robots}).")
        )
    if "nofollow" in robots:
        issues.append(
            _issue("low", "nofollow", page.final_url, f"nofollow is set ({page.robots}).")
        )
    return issues


def _hreflang_issues(page: Page, pages: list[Page]) -> list[Issue]:
    if not page.hreflang:
        return []
    url = page.final_url
    issues: list[Issue] = []
    saw_self = False
    for ref in page.hreflang:
        if not valid_hreflang(ref.lang):
            issues.append(
                _issue(
                    "medium",
                    "hreflang_invalid",
                    url,
                    f'hreflang "{ref.lang}" is not a language tag or x-default.',
                )
            )
        if not ref.is_absolute:
            issues.append(
                _issue(
                    "medium",
                    "hreflang_not_absolute",
                    url,
                    f"hreflang {ref.lang} uses a relative href ({ref.raw_href}).",
                )
            )
        if ref.url == url:
            saw_self = True
            continue
        if ref.url is None:
            continue
        target = _page_for(ref.url, pages)
        if target is None:
            issues.append(
                _issue(
                    "info",
                    "hreflang_target_not_crawled",
                    url,
                    f"hreflang {ref.lang} target {ref.url} was not fetched.",
                )
            )
            continue
        if target.status is not None and target.status >= 400:
            issues.append(
                _issue(
                    "high",
                    "hreflang_target_error",
                    url,
                    f"hreflang {ref.lang} target {ref.url} returned {target.status}.",
                )
            )
            continue
        returns = any(item.url == url for item in target.hreflang)
        if not returns:
            issues.append(
                _issue(
                    "medium",
                    "hreflang_no_return",
                    url,
                    f"{ref.url} ({ref.lang}) does not point back.",
                )
            )
    if not saw_self:
        issues.append(
            _issue(
                "low",
                "hreflang_missing_self",
                url,
                "hreflang alternates are present, and none is this URL.",
            )
        )
    return issues


def _structured_data_issues(page: Page) -> list[Issue]:
    url = page.final_url
    if not page.jsonld:
        return [_issue("info", "jsonld_missing", url, "No JSON-LD block on this document.")]
    issues: list[Issue] = []
    for block in page.jsonld:
        if not block.valid:
            issues.append(
                _issue("high", "jsonld_invalid", url, block.error or "JSON-LD could not be parsed.")
            )
        elif block.empty:
            issues.append(
                _issue("low", "jsonld_empty", url, "JSON-LD parsed but has no @type and no @graph.")
            )
    return issues


def _social_issues(page: Page) -> list[Issue]:
    missing = [name for name in ("og:title", "og:description", "og:image") if not page.og.get(name)]
    if not missing:
        return []
    return [_issue("low", "og_incomplete", page.final_url, "Missing " + ", ".join(missing) + ".")]


def _image_issues(page: Page) -> list[Issue]:
    issues: list[Issue] = []
    for image in page.images:
        if image.alt is None:
            issues.append(
                _issue(
                    "medium",
                    "img_alt_missing",
                    page.final_url,
                    f"Image has no alt attribute: {image.src}",
                )
            )
        elif image.alt.strip() == "":
            issues.append(
                _issue(
                    "info",
                    "img_alt_empty",
                    page.final_url,
                    f"Image has empty alt (fine when decorative): {image.src}",
                )
            )
    return issues


def _size_issues(page: Page, limits: Thresholds) -> list[Issue]:
    if not page.is_html:
        return []
    if page.html_bytes > limits.html_very_large_bytes:
        return [
            _issue(
                "high",
                "html_very_large",
                page.final_url,
                f"HTML document is {page.html_bytes} bytes, above {limits.html_very_large_bytes}.",
            )
        ]
    if page.html_bytes > limits.html_large_bytes:
        return [
            _issue(
                "medium",
                "html_large",
                page.final_url,
                f"HTML document is {page.html_bytes} bytes, above {limits.html_large_bytes}.",
            )
        ]
    return []


def _content_issues(page: Page, limits: Thresholds) -> list[Issue]:
    issues: list[Issue] = []
    if page.indexable() and page.word_count < limits.very_thin_words:
        issues.append(
            _issue(
                "high",
                "very_thin_content",
                page.final_url,
                f"Visible text is {page.word_count} words.",
            )
        )
    elif page.indexable() and page.word_count < limits.thin_words:
        issues.append(
            _issue(
                "medium",
                "thin_content",
                page.final_url,
                f"Visible text is {page.word_count} words.",
            )
        )
    if page.indexable() and page.depth is not None and page.depth >= limits.deep_depth:
        issues.append(
            _issue(
                "low",
                "deep_page",
                page.final_url,
                f"Internal click depth is {page.depth}. The start URL is depth 0.",
            )
        )
    return issues


def _duplicate_issues(documents: list[Page]) -> list[Issue]:
    issues: list[Issue] = []
    issues.extend(
        _duplicates(
            documents,
            code="title_duplicate",
            severity="medium",
            label="Title",
            value_of=lambda page: page.title,
        )
    )
    issues.extend(
        _duplicates(
            documents,
            code="meta_description_duplicate",
            severity="medium",
            label="Meta description",
            value_of=lambda page: page.meta_description,
        )
    )
    return issues


def _duplicates(
    documents: list[Page],
    *,
    code: str,
    severity: Severity,
    label: str,
    value_of: Callable[[Page], str | None],
) -> list[Issue]:
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for page in documents:
        if not page.indexable():
            continue
        raw = value_of(page)
        if not isinstance(raw, str) or not raw.strip():
            continue
        groups[_normalize_text(raw)].append((page.final_url, raw.strip()))
    issues: list[Issue] = []
    for entries in groups.values():
        if len(entries) < 2:
            continue
        urls = [url for url, _raw in entries]
        display = entries[0][1]
        for url in urls:
            others = [other for other in urls if other != url]
            shown = ", ".join(others[:3])
            extra = f" and {len(others) - 3} more" if len(others) > 3 else ""
            issues.append(
                _issue(
                    severity,
                    code,
                    url,
                    f'{label} "{_clip(display)}" is also used on {shown}{extra}.',
                )
            )
    return issues


def _link_issues(
    documents: list[Page],
    pages: list[Page],
    external: list[ExternalCheck],
) -> list[Issue]:
    issues: list[Issue] = []
    external_by_url = {item.url: item for item in external}
    for page in documents:
        seen_targets: set[str] = set()
        for target in page.internal_links:
            if target in seen_targets:
                continue
            seen_targets.add(target)
            outcome = _lookup_page_outcome(target, pages)
            if outcome is None:
                continue
            status, error = outcome
            if error and status is None:
                issues.append(
                    _issue(
                        "high",
                        "broken_internal_link",
                        page.final_url,
                        f"Links to {target}, which failed: {error}",
                    )
                )
            elif status is not None and status >= 400:
                issues.append(
                    _issue(
                        "high",
                        "broken_internal_link",
                        page.final_url,
                        f"Links to {target}, which returned {status}.",
                    )
                )
        seen_external: set[str] = set()
        for target in page.external_links:
            if target in seen_external:
                continue
            seen_external.add(target)
            checked = external_by_url.get(target)
            if checked is None:
                continue
            if checked.error and checked.status is None:
                issues.append(
                    _issue(
                        "medium",
                        "broken_external_link",
                        page.final_url,
                        f"Links to {target}, which failed: {checked.error}",
                    )
                )
            elif checked.status is not None and checked.status >= 400:
                issues.append(
                    _issue(
                        "medium",
                        "broken_external_link",
                        page.final_url,
                        f"Links to {target}, which returned {checked.status}.",
                    )
                )
    return issues


def _sitemap_issues(
    pages: list[Page],
    documents: list[Page],
    sitemap_urls: list[str],
    blocked_urls: list[str],
) -> list[Issue]:
    if not sitemap_urls:
        return []
    listed = set(sitemap_urls)
    represented = set(listed)
    fetched: set[str] = set()
    by_url = {page.url: page for page in pages}
    for page in pages:
        fetched.add(page.url)
        fetched.add(page.final_url)
        for hop in page.hops:
            fetched.add(hop.url)
        if page.url in listed or page.final_url in listed:
            represented.add(page.final_url)
    blocked = set(blocked_urls)
    issues: list[Issue] = []
    for url in sitemap_urls:
        if url in blocked:
            continue
        match = by_url.get(url)
        if match is None:
            if url not in fetched:
                issues.append(
                    _issue(
                        "low",
                        "sitemap_url_not_crawled",
                        url,
                        "Listed in the sitemap and not fetched in this crawl.",
                    )
                )
            continue
        page = match
        if (
            page.loop
            or page.too_many_redirects
            or (page.status is not None and page.status >= 400)
            or (page.error and page.status is None)
        ):
            status = page.status if page.status is not None else "error"
            issues.append(
                _issue("high", "sitemap_url_non_200", url, f"Sitemap URL finished as {status}.")
            )
        elif page.url != page.final_url:
            issues.append(
                _issue(
                    "low",
                    "sitemap_url_redirect",
                    url,
                    f"Sitemap URL redirects to {page.final_url}.",
                )
            )
        if page.parsed and not page.indexable() and "noindex" in (page.robots or "").lower():
            issues.append(
                _issue("medium", "sitemap_url_noindex", url, "Sitemap URL is marked noindex.")
            )
    for document in documents:
        if document.indexable() and document.final_url not in represented:
            issues.append(
                _issue(
                    "low",
                    "orphan_page",
                    document.final_url,
                    "Indexable page is not represented in the sitemap.",
                )
            )
    return issues


def _lookup_status(
    url: str,
    pages: list[Page],
    external_by_url: dict[str, ExternalCheck],
) -> int | None:
    page = _page_for(url, pages)
    if page is not None:
        return page.status
    external = external_by_url.get(url)
    if external is not None:
        return external.status
    return None


def _lookup_page_outcome(url: str, pages: list[Page]) -> tuple[int | None, str | None] | None:
    exact = _page_for(url, pages)
    if exact is not None and exact.url == url:
        return exact.status, exact.error
    for page in pages:
        if any(hop.url == url for hop in page.hops) or page.final_url == url:
            return page.status, page.error
    if exact is not None:
        return exact.status, exact.error
    return None


def _page_for(url: str, pages: list[Page]) -> Page | None:
    for page in pages:
        if page.url == url:
            return page
    for page in pages:
        if page.final_url == url:
            return page
    return None


def _redirect_count(page: Page) -> int:
    if len(page.hops) < 2:
        return 0
    return len(page.hops) - 1


def _chain_message(page: Page, redirects: int) -> str:
    path = " -> ".join(hop.url for hop in page.hops)
    noun = "redirect" if redirects == 1 else "redirects"
    return f"{redirects} {noun}: {path}"


def _status_message(page: Page) -> str:
    if page.url == page.final_url:
        return f"Final status {page.status}."
    return f"Redirected to {page.final_url}, which returned {page.status}."


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _clip(value: str, limit: int = 70) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _issue(severity: Severity, code: str, url: str, message: str) -> Issue:
    require_check(code)
    return Issue(severity, code, url, message)


def _dedupe(issues: list[Issue]) -> list[Issue]:
    seen: set[tuple[str, str, str, str]] = set()
    ordered: list[Issue] = []
    for issue in issues:
        key = (issue.severity, issue.code, issue.url, issue.message)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(issue)
    return ordered


def assign_depths(start_url: str, pages: list[Page]) -> None:
    """Set click depth from the start document along internal links.

    Redirecting URLs are not extra clicks: a link to a redirect uses the final
    document. Unreachable documents, including sitemap-only URLs, stay at
    depth None.
    """
    documents = iter_documents(pages)
    doc_urls = {page.final_url for page in documents}
    alias: dict[str, str] = {}
    for page in pages:
        if page.final_url not in doc_urls:
            continue
        alias.setdefault(page.url, page.final_url)
        alias.setdefault(page.final_url, page.final_url)
        for hop in page.hops:
            alias.setdefault(hop.url, page.final_url)
    entry = start_url if start_url in doc_urls else None
    if entry is None:
        for page in pages:
            if page.url == start_url and page.final_url in doc_urls:
                entry = page.final_url
                break
    adjacency: dict[str, set[str]] = {url: set() for url in doc_urls}
    chosen = {page.final_url: page for page in documents}
    for document in documents:
        for link in document.internal_links:
            target = alias.get(link)
            if target and target != document.final_url and target in adjacency:
                adjacency[document.final_url].add(target)
    distance: dict[str, int] = {}
    if entry is not None:
        distance[entry] = 0
        queue = [entry]
        while queue:
            current = queue.pop(0)
            for nxt in sorted(adjacency[current]):
                if nxt in distance:
                    continue
                distance[nxt] = distance[current] + 1
                queue.append(nxt)
    for page in pages:
        page.depth = None
        if not page.parsed or page.final_url not in distance:
            continue
        if chosen.get(page.final_url) is page:
            page.depth = distance[page.final_url]


def issue_counts(report: AuditReport) -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(SEVERITIES, 0)
    for issue in report.issues:
        counts[issue.severity] += 1
    return counts
