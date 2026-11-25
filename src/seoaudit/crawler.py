"""Polite async crawl.

The fetcher obeys robots.txt, waits between requests, and caps how many pages
and how much HTML it will read. Redirect chains are followed manually so loops
and long chains stay visible in the report.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import httpx

from seoaudit.checks import assign_depths, collect_issues, iter_documents
from seoaudit.models import (
    AuditConfig,
    AuditReport,
    ExternalCheck,
    Hop,
    Page,
    empty_page,
)
from seoaudit.parse import ParsedDocument, charset_from, is_html, parse_html
from seoaudit.robots import Robots, delay_for, parse_robots, robots_allow_all
from seoaudit.score import score_issues
from seoaudit.sitemap import (
    MAX_SITEMAP_URLS,
    MAX_SITEMAPS,
    SitemapProblem,
    SitemapResult,
    parse_sitemap_xml,
)
from seoaudit.urls import SiteScope, dedupe, normalize_url, origin_of
from seoaudit.version import __version__

ProgressCallback = Callable[[int, int, str], None]
REDIRECTS = {301, 302, 303, 307, 308}
ROBOTS_CAP = 20_000


@dataclass(slots=True)
class RawResponse:
    status: int | None
    headers: dict[str, str]
    body: bytes
    truncated: bool
    content_type: str | None
    error: str | None
    elapsed_ms: float
    body_read: bool


class RateLimiter:
    """Space out request starts. Crawl-delay wins when it is slower."""

    def __init__(self, requests_per_second: float, crawl_delay: float | None = None) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        interval = 1.0 / requests_per_second
        if crawl_delay is not None and crawl_delay > interval:
            interval = crawl_delay
        self.interval = interval
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._next > now:
                await asyncio.sleep(self._next - now)
                now = loop.time()
            self._next = now + self.interval


class Scheduler:
    def __init__(
        self,
        *,
        max_pages: int,
        max_depth: int,
        respect_robots: bool,
        robots: Robots,
        user_agent: str,
        queue: asyncio.Queue[str | None],
    ) -> None:
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.respect_robots = respect_robots
        self.robots = robots
        self.user_agent = user_agent
        self.queue = queue
        self.sources: dict[str, str] = {}
        self.depth: dict[str, int] = {}
        self.blocked: list[str] = []
        self.blocked_set: set[str] = set()
        self.referrers: dict[str, str] = {}

    def add(
        self,
        url: str,
        depth: int,
        source: str,
        referrer: str | None = None,
        *,
        force: bool = False,
    ) -> None:
        normalized = normalize_url(url)
        if normalized is None:
            return
        if referrer and normalized not in self.referrers:
            self.referrers[normalized] = referrer
        if normalized in self.sources or normalized in self.blocked_set:
            return
        if not force and depth > self.max_depth:
            return
        if self.respect_robots and not self.robots.allows(normalized, self.user_agent):
            self.blocked_set.add(normalized)
            self.blocked.append(normalized)
            return
        if len(self.sources) >= self.max_pages:
            return
        self.sources[normalized] = source
        self.depth[normalized] = depth
        self.queue.put_nowait(normalized)


class Auditor:
    def __init__(self, config: AuditConfig, on_progress: ProgressCallback | None) -> None:
        self.config = config
        self.on_progress = on_progress
        self.scope = SiteScope(config.start_url, config.include_subdomains)
        self.requests_made = 0
        self.cache: dict[str, RawResponse] = {}
        self.origin_limiter = RateLimiter(config.rate_limit)
        self.external_limiter = RateLimiter(config.rate_limit)
        self.client: httpx.AsyncClient | None = None
        self.scheduler: Scheduler
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def run(self) -> AuditReport:
        started = datetime.now(UTC)
        clock = time.perf_counter()
        timeout = httpx.Timeout(self.config.timeout)
        limits = httpx.Limits(
            max_connections=self.config.concurrency,
            max_keepalive_connections=self.config.concurrency,
        )
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en",
        }
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=self.config.trust_env,
            limits=limits,
            headers=headers,
        ) as client:
            self.client = client
            robots = await self._fetch_robots()
            delay = delay_for(robots, self.config.user_agent)
            robots.crawl_delay = delay
            self.origin_limiter = RateLimiter(self.config.rate_limit, delay)
            sitemap = await self._discover_sitemaps(robots)
            pages = await self._crawl(robots, sitemap)
        assign_depths(self.config.start_url, pages)
        pages.sort(key=lambda page: (page.depth is None, page.depth or 0, page.url))
        external, considered = await self._check_external(pages)
        blocked = sorted(self.scheduler.blocked)
        blocked_referrers = {
            url: self.scheduler.referrers[url] for url in blocked if url in self.scheduler.referrers
        }
        issues = collect_issues(
            pages,
            start_url=self.config.start_url,
            sitemap_urls=sitemap.urls,
            sitemap_sources=sitemap.sources,
            sitemap_problems=sitemap.problems,
            sitemap_truncated=sitemap.truncated,
            robots_unavailable=robots.unavailable,
            robots_error=robots.error,
            external=external,
            blocked_urls=blocked,
            blocked_referrers=blocked_referrers,
            thresholds=self.config.thresholds,
        )
        score = score_issues(issues, has_pages=bool(pages), thresholds=self.config.thresholds)
        finished = datetime.now(UTC)
        robots_text = robots.text
        if len(robots_text) > ROBOTS_CAP:
            robots_text = robots_text[:ROBOTS_CAP] + "\n[truncated]"
        return AuditReport(
            version=__version__,
            start_url=self.config.start_url,
            started_at=_stamp(started),
            finished_at=_stamp(finished),
            duration_seconds=round(time.perf_counter() - clock, 3),
            settings=_settings(self.config, delay, self.origin_limiter.interval),
            robots_status=robots.status,
            robots_found=robots.found,
            robots_unavailable=robots.unavailable,
            robots_error=robots.error,
            robots_text=robots_text,
            robots_sitemaps=list(robots.sitemaps),
            crawl_delay=delay,
            sitemap_sources=sitemap.sources,
            sitemap_urls=sitemap.urls,
            sitemap_errors=[f"{item.url}: {item.message}" for item in sitemap.problems],
            sitemap_truncated=sitemap.truncated,
            pages=pages,
            external=external,
            external_considered=considered,
            blocked_urls=blocked,
            requests_made=self.requests_made,
            issues=issues,
            score=score,
        )

    async def _fetch_robots(self) -> Robots:
        robots_url = origin_of(self.config.start_url) + "/robots.txt"
        raw = await self._follow_text(robots_url, limit=5)
        if raw.error and raw.status is None:
            return robots_allow_all(
                status=None,
                found=False,
                unavailable=True,
                error=f"robots.txt could not be fetched ({raw.error}). Every URL was treated as allowed.",
            )
        status = raw.status or 0
        if status == 404:
            return robots_allow_all(status=404, found=False, unavailable=False, error=None)
        if status in {401, 403} or status >= 500:
            return robots_allow_all(
                status=status,
                found=False,
                unavailable=True,
                error=(
                    f"robots.txt returned {status}. Every URL was treated as allowed "
                    "because the file could not be read."
                ),
                text=raw.body.decode("utf-8", errors="replace"),
            )
        if status != 200:
            return robots_allow_all(
                status=status,
                found=False,
                unavailable=True,
                error=f"robots.txt returned {status}. Every URL was treated as allowed.",
                text=raw.body.decode("utf-8", errors="replace"),
            )
        text = raw.body.decode(charset_from(raw.content_type), errors="replace")
        return parse_robots(text, raw.final_url or robots_url, status=200)

    async def _discover_sitemaps(self, robots: Robots) -> SitemapResult:
        origin = origin_of(self.config.start_url)
        defaults = [origin + "/sitemap.xml", origin + "/sitemap_index.xml"]
        declared: list[str] = []
        for raw_url in robots.sitemaps:
            normalized = normalize_url(raw_url, origin + "/robots.txt")
            if normalized:
                declared.append(normalized)
        default_set = set(defaults)
        declared_set = set(declared)
        queue = dedupe(declared + defaults)
        seen: set[str] = set()
        sources: list[str] = []
        pages: list[str] = []
        problems: list[SitemapProblem] = []
        truncated = False
        while queue and len(seen) < MAX_SITEMAPS:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if (
                self.config.respect_robots
                and self.scope.contains(url)
                and not robots.allows(url, self.config.user_agent)
            ):
                problems.append(
                    SitemapProblem(
                        "sitemap_unreadable",
                        url,
                        "Sitemap URL is disallowed by robots.txt.",
                    )
                )
                continue
            raw = await self._follow_text(url, limit=5)
            optional_miss = url in default_set and url not in declared_set and raw.status == 404
            if optional_miss:
                continue
            if raw.error and raw.status is None:
                problems.append(
                    SitemapProblem("sitemap_unreadable", url, f"Sitemap fetch failed: {raw.error}")
                )
                continue
            if raw.status != 200:
                problems.append(
                    SitemapProblem("sitemap_unreadable", url, f"Sitemap returned {raw.status}.")
                )
                continue
            sources.append(url)
            parsed = parse_sitemap_xml(raw.body)
            if parsed.error:
                problems.append(SitemapProblem("sitemap_invalid", url, parsed.error))
                continue
            for page_url in parsed.page_urls:
                normalized = normalize_url(page_url, url)
                if normalized and self.scope.contains(normalized):
                    pages.append(normalized)
            for child in parsed.child_urls:
                normalized = normalize_url(child, url)
                if normalized and normalized not in seen:
                    queue.append(normalized)
                    declared_set.add(normalized)
            if len(pages) >= MAX_SITEMAP_URLS:
                pages = pages[:MAX_SITEMAP_URLS]
                truncated = True
                break
        if queue and len(seen) >= MAX_SITEMAPS:
            truncated = True
        return SitemapResult(sources, dedupe(pages), problems, truncated)

    async def _crawl(self, robots: Robots, sitemap: SitemapResult) -> list[Page]:
        self.scheduler = Scheduler(
            max_pages=self.config.max_pages,
            max_depth=self.config.max_depth,
            respect_robots=self.config.respect_robots,
            robots=robots,
            user_agent=self.config.user_agent,
            queue=self.queue,
        )
        pages: list[Page] = []
        workers = [asyncio.create_task(self._worker(pages)) for _ in range(self.config.concurrency)]
        self.scheduler.add(self.config.start_url, 0, "start")
        await self.queue.join()
        for url in sitemap.urls:
            self.scheduler.add(url, 0, "sitemap", force=True)
        await self.queue.join()
        for _ in workers:
            self.queue.put_nowait(None)
        await asyncio.gather(*workers)
        return pages

    async def _worker(self, pages: list[Page]) -> None:
        while True:
            url = await self.queue.get()
            try:
                if url is None:
                    return
                source = self.scheduler.sources.get(url, "link")
                try:
                    page = await self._fetch_page(url, source)
                except Exception as exc:
                    page = empty_page(url)
                    page.source = source
                    page.error = f"{exc.__class__.__name__}: {exc}"[:300]
                pages.append(page)
                if self.on_progress is not None:
                    self.on_progress(len(pages), len(self.scheduler.sources), url)
                self._enqueue_links(page)
            finally:
                self.queue.task_done()

    def _enqueue_links(self, page: Page) -> None:
        if not page.parsed:
            return
        parent_depth = self.scheduler.depth.get(page.url, 0)
        for link in page.internal_links:
            self.scheduler.add(link, parent_depth + 1, "link", referrer=page.final_url)
        for alternate in _alternates(page):
            if self.scope.contains(alternate):
                self.scheduler.add(alternate, parent_depth, "alternate", referrer=page.final_url)

    async def _fetch_page(self, url: str, source: str) -> Page:
        page = empty_page(url)
        page.source = source
        hops: list[Hop] = []
        current = url
        followed = 0
        elapsed = 0.0
        while True:
            if any(hop.url == current for hop in hops):
                page.loop = True
                page.hops = hops
                page.final_url = current
                page.status = hops[-1].status if hops else None
                page.elapsed_ms = round(elapsed, 1)
                return page
            raw = await self._request(current, mode="html")
            elapsed += raw.elapsed_ms
            if raw.error and raw.status is None:
                page.hops = hops
                page.final_url = current
                page.error = raw.error
                page.elapsed_ms = round(elapsed, 1)
                return page
            status = raw.status or 0
            hops.append(Hop(current, status))
            if status in REDIRECTS:
                location = raw.headers.get("location")
                nxt = normalize_url(location, current) if location else None
                if nxt is None:
                    page.missing_location = True
                    page.hops = hops
                    page.final_url = current
                    page.status = status
                    page.elapsed_ms = round(elapsed, 1)
                    return page
                if followed >= self.config.max_redirects:
                    page.too_many_redirects = True
                    page.hops = hops
                    page.final_url = current
                    page.status = status
                    page.elapsed_ms = round(elapsed, 1)
                    return page
                followed += 1
                current = nxt
                continue
            page.hops = hops
            page.final_url = current
            page.status = status
            page.error = raw.error
            page.content_type = raw.content_type
            page.is_html = is_html(raw.content_type)
            page.truncated = raw.truncated
            page.offsite_redirect = (
                bool(hops) and not self.scope.contains(current) and current != url
            )
            page.html_bytes = _html_size(raw, page.is_html)
            page.elapsed_ms = round(elapsed, 1)
            if status == 200 and page.is_html and self.scope.contains(current) and raw.body_read:
                text = _decode(raw)
                document = parse_html(
                    text,
                    current,
                    link_header=raw.headers.get("link"),
                    robots_header=raw.headers.get("x-robots-tag"),
                )
                _apply_document(page, document, self.scope)
            return page

    async def _follow_text(self, url: str, *, limit: int) -> "Followed":
        current = url
        seen: set[str] = set()
        last = RawResponse(None, {}, b"", False, None, "not requested", 0.0, False)
        for _ in range(limit + 1):
            if current in seen:
                failed = RawResponse(None, {}, b"", False, None, "redirect loop", 0.0, False)
                return Followed(failed, current)
            seen.add(current)
            last = await self._request(current, mode="text")
            if last.status not in REDIRECTS:
                return Followed(last, current)
            location = last.headers.get("location")
            nxt = normalize_url(location, current) if location else None
            if nxt is None:
                return Followed(last, current)
            current = nxt
        failed = RawResponse(
            last.status,
            last.headers,
            last.body,
            last.truncated,
            last.content_type,
            "too many redirects",
            last.elapsed_ms,
            last.body_read,
        )
        return Followed(failed, current)

    async def _request(self, url: str, *, mode: str) -> RawResponse:
        cached = self.cache.get(url)
        if cached and cached.error is None and (cached.body_read or mode == "none"):
            return cached
        if self.client is None:
            raise RuntimeError("HTTP client is not open")
        limiter = self.origin_limiter if self.scope.contains(url) else self.external_limiter
        await limiter.acquire()
        self.requests_made += 1
        started = time.perf_counter()
        try:
            async with self.client.stream("GET", url) as response:
                headers = _header_map(response)
                status = response.status_code
                content_type = response.headers.get("content-type")
                want_body = status == 200 and (
                    mode == "text"
                    or (mode == "html" and is_html(content_type) and self.scope.contains(url))
                )
                if want_body:
                    body, truncated = await _read_limited(response, self.config.max_body_bytes)
                    body_read = True
                else:
                    await _read_limited(response, 8192)
                    body = b""
                    truncated = False
                    body_read = False
                raw = RawResponse(
                    status=status,
                    headers=headers,
                    body=body,
                    truncated=truncated,
                    content_type=content_type,
                    error=None,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    body_read=body_read,
                )
        except httpx.TimeoutException:
            raw = RawResponse(
                None,
                {},
                b"",
                False,
                None,
                "timed out",
                (time.perf_counter() - started) * 1000,
                False,
            )
        except httpx.HTTPError as exc:
            raw = RawResponse(
                None,
                {},
                b"",
                False,
                None,
                exc.__class__.__name__,
                (time.perf_counter() - started) * 1000,
                False,
            )
        if raw.error is None:
            self.cache[url] = raw
        return raw

    async def _check_external(self, pages: list[Page]) -> tuple[list[ExternalCheck], int]:
        if not self.config.check_external or self.config.max_external == 0:
            return [], 0
        targets = _external_targets(pages, self.scope)
        considered = len(targets)
        chosen = targets[: self.config.max_external]
        if not chosen:
            return [], considered
        semaphore = asyncio.Semaphore(self.config.concurrency)

        async def one(url: str) -> ExternalCheck:
            async with semaphore:
                return await self._external_status(url)

        # The crawl client is closed after _crawl returns. External checks need
        # their own client so the connection pool is still open.
        timeout = httpx.Timeout(self.config.timeout)
        headers = {"User-Agent": self.config.user_agent, "Accept": "*/*"}
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=self.config.trust_env,
            headers=headers,
        ) as client:
            self.client = client
            checked = await asyncio.gather(*(one(url) for url in chosen))
        return list(checked), considered

    async def _external_status(self, url: str) -> ExternalCheck:
        current = url
        seen: set[str] = set()
        for _ in range(self.config.max_redirects + 1):
            if current in seen:
                return ExternalCheck(url, None, "redirect loop", current)
            seen.add(current)
            raw = await self._request(current, mode="none")
            if raw.error and raw.status is None:
                return ExternalCheck(url, None, raw.error, current)
            if raw.status not in REDIRECTS:
                return ExternalCheck(url, raw.status, None, current)
            location = raw.headers.get("location")
            nxt = normalize_url(location, current) if location else None
            if nxt is None:
                return ExternalCheck(url, raw.status, "redirect missing location", current)
            current = nxt
        return ExternalCheck(url, None, "too many redirects", current)


@dataclass(slots=True)
class Followed:
    raw: RawResponse
    final_url: str

    @property
    def status(self) -> int | None:
        return self.raw.status

    @property
    def error(self) -> str | None:
        return self.raw.error

    @property
    def body(self) -> bytes:
        return self.raw.body

    @property
    def content_type(self) -> str | None:
        return self.raw.content_type


def _apply_document(page: Page, document: ParsedDocument, scope: SiteScope) -> None:
    page.title = document.title
    page.meta_description = document.meta_description
    page.robots = document.robots
    page.h1s = document.h1s
    page.h1_empty = document.h1_empty
    page.canonicals = document.canonicals
    page.hreflang = document.hreflang
    page.jsonld = document.jsonld
    page.og = document.og
    page.images = document.images
    page.word_count = document.word_count
    page.parsed = True
    page.is_html = True
    internal: list[str] = []
    external: list[str] = []
    for link in dedupe(document.links):
        if scope.contains(link):
            internal.append(link)
        else:
            external.append(link)
    page.internal_links = internal
    page.external_links = external


def _alternates(page: Page) -> list[str]:
    found = list(page.canonicals)
    for ref in page.hreflang:
        if ref.url:
            found.append(ref.url)
    return dedupe(found)


def _external_targets(pages: list[Page], scope: SiteScope) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def push(url: str | None) -> None:
        if not url or url in seen or scope.contains(url):
            return
        seen.add(url)
        found.append(url)

    for page in iter_documents(pages):
        for link in page.external_links:
            push(link)
        for canonical in page.canonicals:
            push(canonical)
        for ref in page.hreflang:
            push(ref.url)
    return found


def _html_size(raw: RawResponse, html: bool) -> int:
    downloaded = len(raw.body)
    declared = _content_length(raw.headers)
    if raw.truncated and declared and declared > downloaded:
        return declared
    if html:
        return downloaded
    return declared or 0


def _content_length(headers: dict[str, str]) -> int | None:
    raw = headers.get("content-length", "")
    if raw.isdigit():
        return int(raw)
    return None


def _decode(raw: RawResponse) -> str:
    encoding = charset_from(raw.content_type)
    try:
        return raw.body.decode(encoding, errors="replace")
    except LookupError:
        return raw.body.decode("utf-8", errors="replace")


def _header_map(response: httpx.Response) -> dict[str, str]:
    keys = {key.lower() for key in response.headers}
    return {key: ", ".join(response.headers.get_list(key)) for key in keys}


async def _read_limited(response: httpx.Response, limit: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    size = 0
    truncated = False
    async for chunk in response.aiter_bytes():
        if size >= limit:
            truncated = True
            break
        chunks.append(chunk)
        size += len(chunk)
    body = b"".join(chunks)
    if size > limit:
        body = body[:limit]
        truncated = True
    return body, truncated


def _settings(config: AuditConfig, crawl_delay: float | None, interval: float) -> dict[str, object]:
    return {
        "max_pages": config.max_pages,
        "max_depth": config.max_depth,
        "rate_limit": config.rate_limit,
        "concurrency": config.concurrency,
        "timeout": config.timeout,
        "max_redirects": config.max_redirects,
        "user_agent": config.user_agent,
        "check_external": config.check_external,
        "max_external": config.max_external,
        "respect_robots": config.respect_robots,
        "include_subdomains": config.include_subdomains,
        "max_body_bytes": config.max_body_bytes,
        "trust_env": config.trust_env,
        "thresholds": asdict(config.thresholds),
        "crawl_delay": crawl_delay,
        "effective_request_interval": interval,
    }


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


async def run_audit(
    config: AuditConfig,
    on_progress: ProgressCallback | None = None,
) -> AuditReport:
    """Crawl ``config.start_url`` and return the audit. Nothing is written to disk."""
    return await Auditor(config, on_progress).run()
