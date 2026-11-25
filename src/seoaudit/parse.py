"""HTML extraction for the on-page checks.

The parser reads the raw response. It does not execute JavaScript, and it does
not see markup that a browser would inject later.
"""

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from seoaudit.models import HreflangRef, ImageRef, JsonLdBlock
from seoaudit.urls import normalize_url

_CHARSET = re.compile(r"charset=([^\s;]+)", re.IGNORECASE)
_LANG = re.compile(r"^(x-default|[a-z]{2,3}(?:-[a-z0-9]{2,8})*)$", re.IGNORECASE)


@dataclass(slots=True)
class ParsedDocument:
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
    links: list[str]


def is_html(content_type: str | None) -> bool:
    if not content_type:
        return False
    mime = content_type.split(";", 1)[0].strip().lower()
    return mime in {"text/html", "application/xhtml+xml"}


def charset_from(content_type: str | None) -> str:
    if not content_type:
        return "utf-8"
    match = _CHARSET.search(content_type)
    if not match:
        return "utf-8"
    return match.group(1).strip("\"'")


def parse_html(
    text: str,
    page_url: str,
    *,
    link_header: str | None = None,
    robots_header: str | None = None,
) -> ParsedDocument:
    soup = BeautifulSoup(text, "html.parser")
    base_tag = soup.find("base", href=True)
    base_url = page_url
    if base_tag is not None:
        raw_base = _as_str(base_tag.get("href"))
        if raw_base:
            resolved = normalize_url(raw_base, page_url)
            if resolved:
                base_url = resolved

    title = _title(soup)
    meta_description = _meta_content(soup, {"description"})
    robots_meta = _meta_content(soup, {"robots", "googlebot"})
    robots = _join_robots(robots_meta, robots_header)
    h1s, h1_empty = _h1s(soup)
    canonicals = _canonicals(soup, base_url)
    canonicals.extend(_canonicals_from_link_header(link_header, base_url))
    canonicals = _unique(canonicals)
    hreflang = _hreflang(soup, base_url)
    jsonld = _jsonld(soup)
    og = _open_graph(soup)
    images = _images(soup, base_url)
    links = _links(soup, base_url)
    words = _word_count(soup)
    return ParsedDocument(
        title=title,
        meta_description=meta_description,
        robots=robots,
        h1s=h1s,
        h1_empty=h1_empty,
        canonicals=canonicals,
        hreflang=hreflang,
        jsonld=jsonld,
        og=og,
        images=images,
        word_count=words,
        links=links,
    )


def _title(soup: Any) -> str | None:
    tag = soup.find("title")
    if tag is None:
        return None
    text = tag.get_text(" ", strip=True)
    return text or None


def _meta_content(soup: Any, names: set[str]) -> str | None:
    chunks: list[str] = []
    for tag in soup.find_all("meta"):
        name = _as_str(tag.get("name"))
        if name is None or name.lower() not in names:
            continue
        content = _as_str(tag.get("content"))
        if content:
            chunks.append(content.strip())
    if not chunks:
        return None
    return ", ".join(chunks)


def _join_robots(meta: str | None, header: str | None) -> str | None:
    parts = [part.strip() for part in (meta, header) if part and part.strip()]
    if not parts:
        return None
    return ", ".join(parts)


def _h1s(soup: Any) -> tuple[list[str], int]:
    found: list[str] = []
    empty = 0
    for tag in soup.find_all("h1"):
        text = tag.get_text(" ", strip=True)
        if text:
            found.append(text)
        else:
            empty += 1
    return found, empty


def _canonicals(soup: Any, base_url: str) -> list[str]:
    found: list[str] = []
    for tag in soup.find_all("link"):
        if "canonical" not in _rel_tokens(tag):
            continue
        href = _as_str(tag.get("href"))
        if not href:
            continue
        normalized = normalize_url(href, base_url)
        if normalized:
            found.append(normalized)
    return found


def _hreflang(soup: Any, base_url: str) -> list[HreflangRef]:
    found: list[HreflangRef] = []
    for tag in soup.find_all("link"):
        if "alternate" not in _rel_tokens(tag):
            continue
        lang = _as_str(tag.get("hreflang"))
        href = _as_str(tag.get("href"))
        if not lang or not href:
            continue
        absolute = urlsplit(href.strip()).scheme in {"http", "https"}
        found.append(
            HreflangRef(
                lang=lang.strip(),
                raw_href=href.strip(),
                url=normalize_url(href, base_url),
                is_absolute=absolute,
            )
        )
    return found


def _jsonld(soup: Any) -> list[JsonLdBlock]:
    blocks: list[JsonLdBlock] = []
    for tag in soup.find_all("script"):
        kind = _as_str(tag.get("type"))
        if kind is None or kind.lower() != "application/ld+json":
            continue
        raw = tag.string if tag.string is not None else tag.get_text()
        raw = (raw or "").strip()
        if not raw:
            blocks.append(JsonLdBlock(False, "JSON-LD block is empty", [], True))
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            blocks.append(JsonLdBlock(False, f"Invalid JSON ({exc.msg})", [], False))
            continue
        types = _schema_types(data)
        blocks.append(JsonLdBlock(True, None, types, _jsonld_empty(data)))
    return blocks


def _schema_types(data: object) -> list[str]:
    found: list[str] = []
    if isinstance(data, list):
        for item in data:
            found.extend(_schema_types(item))
        return found
    if not isinstance(data, dict):
        return found
    kind = data.get("@type")
    if isinstance(kind, str):
        found.append(kind)
    elif isinstance(kind, list):
        found.extend(str(item) for item in kind)
    graph = data.get("@graph")
    if isinstance(graph, list):
        found.extend(_schema_types(graph))
    return found


def _jsonld_empty(data: object) -> bool:
    if data in ({}, [], None):
        return True
    if isinstance(data, list):
        return all(_jsonld_empty(item) for item in data) or not data
    if not isinstance(data, dict):
        return False
    meaningful = [key for key in data if key != "@context"]
    return not meaningful


def _open_graph(soup: Any) -> dict[str, str]:
    found: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        prop = _as_str(tag.get("property")) or _as_str(tag.get("name"))
        if prop is None or not prop.lower().startswith("og:"):
            continue
        content = _as_str(tag.get("content"))
        if content is None:
            continue
        found.setdefault(prop.lower(), content.strip())
    return found


def _images(soup: Any, base_url: str) -> list[ImageRef]:
    found: list[ImageRef] = []
    for tag in soup.find_all("img"):
        src = _as_str(tag.get("src")) or _as_str(tag.get("data-src"))
        if not src:
            continue
        absolute = normalize_url(src, base_url) or src.strip()
        alt = _as_str(tag.get("alt")) or "" if tag.has_attr("alt") else None
        found.append(ImageRef(absolute, alt))
    return found


def _links(soup: Any, base_url: str) -> list[str]:
    found: list[str] = []
    for tag in soup.find_all("a"):
        href = _as_str(tag.get("href"))
        if not href:
            continue
        normalized = normalize_url(href, base_url)
        if normalized:
            found.append(normalized)
    return found


def _word_count(soup: Any) -> int:
    root = soup.body if soup.body is not None else soup
    for tag in root.find_all(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    text = root.get_text(" ", strip=True)
    if not text:
        return 0
    return len(re.findall(r"\S+", text))


def _canonicals_from_link_header(header: str | None, base_url: str) -> list[str]:
    if not header:
        return []
    found: list[str] = []
    for part in _split_link_header(header):
        match = re.match(r"\s*<([^>]+)>\s*;\s*(.*)$", part.strip())
        if not match:
            continue
        href, params = match.group(1), match.group(2)
        rels: set[str] = set()
        for attr in params.split(";"):
            if "=" not in attr:
                continue
            key, value = attr.split("=", 1)
            if key.strip().lower() != "rel":
                continue
            token = value.strip().strip('"').strip("'")
            rels.update(piece.lower() for piece in token.split())
        if "canonical" not in rels:
            continue
        normalized = normalize_url(href, base_url)
        if normalized:
            found.append(normalized)
    return found


def _split_link_header(header: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    in_angles = False
    for char in header:
        if char == "<":
            in_angles = True
            buf.append(char)
        elif char == ">":
            in_angles = False
            buf.append(char)
        elif char == "," and not in_angles:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    if buf:
        parts.append("".join(buf))
    return parts


def _rel_tokens(tag: Any) -> set[str]:
    raw = tag.get("rel")
    if raw is None:
        return set()
    parts = [str(item) for item in raw] if isinstance(raw, list) else str(raw).split()
    return {part.lower() for part in parts}


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    text = str(value).strip()
    return text or None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def valid_hreflang(lang: str) -> bool:
    return _LANG.fullmatch(lang.strip()) is not None
