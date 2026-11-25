"""Stable descriptions for every issue code the auditor can emit."""

from dataclasses import dataclass

from seoaudit.thresholds import Thresholds

CATEGORIES: tuple[str, ...] = ("crawl", "links", "indexation", "metadata", "content")


@dataclass(frozen=True, slots=True)
class Check:
    code: str
    category: str
    summary: str


def _catalog(thresholds: Thresholds) -> dict[str, Check]:
    t = thresholds
    rows = [
        Check(
            "fetch_failed",
            "crawl",
            "The URL could not be fetched because the request timed out or the connection failed.",
        ),
        Check("http_server_error", "crawl", "The final response was a 5xx server error."),
        Check("http_client_error", "crawl", "The final response was a 4xx client error."),
        Check(
            "rate_limited",
            "crawl",
            "The server returned 429 Too Many Requests. The crawl does not retry.",
        ),
        Check("redirect_loop", "crawl", "The redirect chain visits the same URL twice."),
        Check(
            "too_many_redirects",
            "crawl",
            "Redirects exceeded the configured maximum before a final response.",
        ),
        Check(
            "redirect_missing_location",
            "crawl",
            "A 3xx response did not include a usable Location header.",
        ),
        Check(
            "redirect_chain",
            "crawl",
            "The URL redirects more than once. Two hops are medium; three or more are high.",
        ),
        Check("redirect_offsite", "crawl", "The URL redirects to a different site."),
        Check(
            "response_truncated",
            "crawl",
            "The HTML body was longer than the download limit and was cut off, so on-page checks may be incomplete.",
        ),
        Check(
            "robots_unavailable",
            "crawl",
            "robots.txt could not be used. A 5xx or a forbidden robots.txt is treated as no restrictions and called out here.",
        ),
        Check(
            "blocked_by_robots", "crawl", "robots.txt disallows this URL, so it was not fetched."
        ),
        Check(
            "broken_internal_link",
            "links",
            "An internal link points at a URL in this crawl that returned an error or failed.",
        ),
        Check(
            "broken_external_link",
            "links",
            "An external URL returned an error or could not be fetched.",
        ),
        Check(
            "canonical_missing",
            "indexation",
            "The HTML document has no canonical URL in a link element or a Link header.",
        ),
        Check(
            "canonical_multiple",
            "indexation",
            "The document declares more than one distinct canonical URL.",
        ),
        Check("canonical_non_self", "indexation", "The canonical URL is not this document."),
        Check(
            "canonical_target_error",
            "indexation",
            "A canonical URL was fetched and the final status was not successful.",
        ),
        Check(
            "noindex",
            "indexation",
            "The document sends noindex in a robots meta tag or an X-Robots-Tag header.",
        ),
        Check(
            "nofollow",
            "indexation",
            "The document sends nofollow in a robots meta tag or an X-Robots-Tag header.",
        ),
        Check(
            "hreflang_invalid",
            "indexation",
            "An hreflang value is not a BCP 47-style language tag and is not x-default.",
        ),
        Check(
            "hreflang_not_absolute",
            "indexation",
            "An hreflang href is relative. Google asks for absolute URLs.",
        ),
        Check(
            "hreflang_missing_self",
            "indexation",
            "The document lists hreflang alternates, and none of them is itself.",
        ),
        Check(
            "hreflang_no_return",
            "indexation",
            "An alternate language URL does not point back to this document.",
        ),
        Check(
            "hreflang_target_error",
            "indexation",
            "An hreflang target was fetched and the final status was not successful.",
        ),
        Check(
            "hreflang_target_not_crawled",
            "indexation",
            "An hreflang target was not fetched, so a return link could not be checked.",
        ),
        Check(
            "sitemap_missing",
            "indexation",
            "No sitemap was found from robots.txt or from /sitemap.xml and /sitemap_index.xml.",
        ),
        Check(
            "sitemap_invalid",
            "indexation",
            "A sitemap response was not a urlset or a sitemap index.",
        ),
        Check(
            "sitemap_unreadable",
            "indexation",
            "A sitemap URL declared by the site could not be fetched.",
        ),
        Check(
            "sitemap_truncated",
            "indexation",
            "The sitemap contained more URLs or child sitemaps than this crawl keeps.",
        ),
        Check(
            "orphan_page",
            "indexation",
            "An indexable page was crawled and is not represented in the sitemap.",
        ),
        Check(
            "sitemap_url_not_crawled",
            "indexation",
            "A same-site sitemap URL was not fetched. The page budget or the depth limit was already used.",
        ),
        Check(
            "sitemap_url_non_200",
            "indexation",
            "A sitemap URL was fetched and the final status was not 200.",
        ),
        Check(
            "sitemap_url_redirect",
            "indexation",
            "A sitemap URL redirects. Sitemaps should list the final URL.",
        ),
        Check("sitemap_url_noindex", "indexation", "A sitemap URL is marked noindex."),
        Check("title_missing", "metadata", "The HTML document has no <title>."),
        Check(
            "title_too_short", "metadata", f"The title is shorter than {t.title_min} characters."
        ),
        Check("title_too_long", "metadata", f"The title is longer than {t.title_max} characters."),
        Check(
            "title_duplicate", "metadata", "The same title is used on more than one indexable URL."
        ),
        Check("meta_description_missing", "metadata", "The HTML document has no meta description."),
        Check(
            "meta_description_too_short",
            "metadata",
            f"The meta description is shorter than {t.meta_min} characters.",
        ),
        Check(
            "meta_description_too_long",
            "metadata",
            f"The meta description is longer than {t.meta_max} characters.",
        ),
        Check(
            "meta_description_duplicate",
            "metadata",
            "The same meta description is used on more than one indexable URL.",
        ),
        Check("h1_missing", "metadata", "The HTML document has no H1."),
        Check("h1_multiple", "metadata", "The HTML document has more than one H1."),
        Check("h1_empty", "metadata", "The HTML document has an empty H1 element."),
        Check(
            "og_incomplete",
            "metadata",
            "Open Graph is missing og:title, og:description, or og:image.",
        ),
        Check(
            "jsonld_missing",
            "content",
            "The document has no JSON-LD block. This is informational; not every URL needs structured data.",
        ),
        Check("jsonld_invalid", "content", "A JSON-LD block could not be parsed as JSON."),
        Check(
            "jsonld_empty", "content", "A JSON-LD block parsed, but it has no @type and no @graph."
        ),
        Check("img_alt_missing", "content", "An image has no alt attribute."),
        Check(
            "img_alt_empty",
            "content",
            "An image has an empty alt attribute. That is valid for a decorative image; confirm it is intentional.",
        ),
        Check(
            "html_large",
            "content",
            f"The HTML document is larger than {t.html_large_bytes // 1000} KB. This is the document size, not the weight of images, CSS, and scripts.",
        ),
        Check(
            "html_very_large",
            "content",
            f"The HTML document is larger than {t.html_very_large_bytes // 1000} KB.",
        ),
        Check(
            "deep_page",
            "content",
            f"The shortest internal click path from the start URL is {t.deep_depth} or more clicks.",
        ),
        Check(
            "very_thin_content",
            "content",
            f"The document has fewer than {t.very_thin_words} visible words.",
        ),
        Check(
            "thin_content", "content", f"The document has fewer than {t.thin_words} visible words."
        ),
    ]
    catalog = {row.code: row for row in rows}
    if len(catalog) != len(rows):
        raise RuntimeError("Duplicate issue codes in the catalog")
    unknown = {row.category for row in rows} - set(CATEGORIES)
    if unknown:
        raise RuntimeError(f"Unknown categories: {sorted(unknown)}")
    return catalog


DEFAULT_CATALOG = _catalog(Thresholds())


def catalog_for(thresholds: Thresholds) -> dict[str, Check]:
    if thresholds == Thresholds():
        return DEFAULT_CATALOG
    return _catalog(thresholds)


def require_check(code: str, thresholds: Thresholds | None = None) -> Check:
    found = catalog_for(thresholds or Thresholds()).get(code)
    if found is None:
        raise KeyError(code)
    return found
