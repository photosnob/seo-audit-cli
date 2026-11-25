"""Data passed between the crawler, the checks, and the report writers."""

from dataclasses import dataclass, field
from typing import Literal

from seoaudit.thresholds import Thresholds

Severity = Literal["critical", "high", "medium", "low", "info"]
SEVERITIES: tuple[Severity, ...] = ("critical", "high", "medium", "low", "info")

DEFAULT_USER_AGENT = "SeoAuditBot/0.1 (+https://github.com/photosnob/seo-audit-cli)"


@dataclass(frozen=True, slots=True)
class Hop:
    url: str
    status: int


@dataclass(frozen=True, slots=True)
class HreflangRef:
    lang: str
    raw_href: str
    url: str | None
    is_absolute: bool


@dataclass(frozen=True, slots=True)
class JsonLdBlock:
    valid: bool
    error: str | None
    types: list[str]
    empty: bool


@dataclass(frozen=True, slots=True)
class ImageRef:
    src: str
    alt: str | None


@dataclass(slots=True)
class Page:
    url: str
    final_url: str
    status: int | None
    error: str | None
    hops: list[Hop]
    loop: bool
    too_many_redirects: bool
    missing_location: bool
    offsite_redirect: bool
    content_type: str | None
    is_html: bool
    parsed: bool
    depth: int | None
    html_bytes: int
    elapsed_ms: float
    title: str | None
    meta_description: str | None
    robots: str | None
    h1s: list[str]
    h1_empty: int
    canonicals: list[str]
    hreflang: list[HreflangRef]
    jsonld: list[JsonLdBlock]
    og: dict[str, str]
    images: list[ImageRef]
    word_count: int
    internal_links: list[str]
    external_links: list[str]
    truncated: bool
    source: str

    def indexable(self) -> bool:
        """True for an HTML 200 document that is not marked noindex."""
        if not self.parsed or self.status != 200:
            return False
        return "noindex" not in (self.robots or "").lower()


def empty_page(url: str) -> Page:
    return Page(
        url=url,
        final_url=url,
        status=None,
        error=None,
        hops=[],
        loop=False,
        too_many_redirects=False,
        missing_location=False,
        offsite_redirect=False,
        content_type=None,
        is_html=False,
        parsed=False,
        depth=None,
        html_bytes=0,
        elapsed_ms=0.0,
        title=None,
        meta_description=None,
        robots=None,
        h1s=[],
        h1_empty=0,
        canonicals=[],
        hreflang=[],
        jsonld=[],
        og={},
        images=[],
        word_count=0,
        internal_links=[],
        external_links=[],
        truncated=False,
        source="link",
    )


@dataclass(slots=True)
class ExternalCheck:
    url: str
    status: int | None
    error: str | None
    final_url: str | None


@dataclass(frozen=True, slots=True)
class Issue:
    severity: Severity
    code: str
    url: str
    message: str

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"Unknown severity: {self.severity}")


@dataclass(frozen=True, slots=True)
class Deduction:
    code: str
    severity: str
    category: str
    count: int
    points: float


@dataclass(slots=True)
class Score:
    overall: float | None
    deductions: list[Deduction]
    categories: dict[str, float | None]


@dataclass(slots=True)
class AuditConfig:
    start_url: str
    max_pages: int = 100
    max_depth: int = 6
    rate_limit: float = 2.0
    concurrency: int = 4
    timeout: float = 15.0
    max_redirects: int = 10
    user_agent: str = DEFAULT_USER_AGENT
    check_external: bool = True
    max_external: int = 50
    respect_robots: bool = True
    include_subdomains: bool = False
    max_body_bytes: int = 1_000_000
    trust_env: bool = True
    thresholds: Thresholds = field(default_factory=Thresholds)

    def __post_init__(self) -> None:
        from seoaudit.urls import ensure_scheme, normalize_url

        if self.max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if self.max_depth < 0:
            raise ValueError("max_depth must be at least 0")
        if self.rate_limit <= 0:
            raise ValueError("rate_limit must be positive")
        if self.concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects must be at least 0")
        if self.max_external < 0:
            raise ValueError("max_external must be at least 0")
        if self.max_body_bytes < 1:
            raise ValueError("max_body_bytes must be at least 1")
        if not self.user_agent.strip():
            raise ValueError("user_agent must not be empty")
        normalized = normalize_url(ensure_scheme(self.start_url))
        if normalized is None:
            raise ValueError(f"Invalid start URL: {self.start_url}")
        self.start_url = normalized


@dataclass(slots=True)
class AuditReport:
    version: str
    start_url: str
    started_at: str
    finished_at: str
    duration_seconds: float
    settings: dict[str, object]
    robots_status: int | None
    robots_found: bool
    robots_unavailable: bool
    robots_error: str | None
    robots_text: str
    robots_sitemaps: list[str]
    crawl_delay: float | None
    sitemap_sources: list[str]
    sitemap_urls: list[str]
    sitemap_errors: list[str]
    sitemap_truncated: bool
    pages: list[Page]
    external: list[ExternalCheck]
    external_considered: int
    blocked_urls: list[str]
    requests_made: int
    issues: list[Issue]
    score: Score
