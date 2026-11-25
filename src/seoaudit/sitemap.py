"""Sitemap discovery and XML parsing.

Child sitemaps are fetched one level at a time, up to a fixed cap, so a
sitemap index cannot send the crawler into an unbounded loop. DOCTYPE
declarations are rejected to avoid XML entity expansion.
"""

import gzip
from dataclasses import dataclass
from xml.etree import ElementTree as ET

MAX_SITEMAP_URLS = 10_000
MAX_SITEMAPS = 50
MAX_SITEMAP_BYTES = 20_000_000


@dataclass(slots=True)
class SitemapDocument:
    page_urls: list[str]
    child_urls: list[str]
    error: str | None


@dataclass(frozen=True, slots=True)
class SitemapProblem:
    code: str
    url: str
    message: str


@dataclass(slots=True)
class SitemapResult:
    sources: list[str]
    urls: list[str]
    problems: list[SitemapProblem]
    truncated: bool


def parse_sitemap_xml(payload: bytes) -> SitemapDocument:
    if payload.startswith(b"\x1f\x8b"):
        try:
            payload = gzip.decompress(payload)
        except OSError as exc:
            return SitemapDocument([], [], f"Gzip sitemap could not be decompressed ({exc})")
    if len(payload) > MAX_SITEMAP_BYTES:
        return SitemapDocument([], [], "Sitemap is larger than the parser limit")
    text = payload.decode("utf-8-sig", errors="replace")
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return SitemapDocument([], [], "Sitemap DTD and entity declarations are not accepted")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return SitemapDocument([], [], f"Sitemap XML could not be parsed ({exc})")
    kind = _local(root.tag)
    if kind == "urlset":
        return SitemapDocument(_locs(root, "url"), [], None)
    if kind == "sitemapindex":
        return SitemapDocument([], _locs(root, "sitemap"), None)
    return SitemapDocument([], [], f"Unexpected sitemap root <{kind or 'unknown'}>")


def _locs(root: ET.Element, parent_name: str) -> list[str]:
    found: list[str] = []
    for node in list(root):
        if _local(node.tag) != parent_name:
            continue
        for child in list(node):
            if _local(child.tag) == "loc" and child.text and child.text.strip():
                found.append(child.text.strip())
                break
    return found


def _local(tag: str) -> str:
    if not tag:
        return ""
    return tag.rsplit("}", 1)[-1].lower()
