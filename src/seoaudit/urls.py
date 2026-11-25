"""URL normalization and same-site checks."""

from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit


def ensure_scheme(url: str) -> str:
    """Prepend https:// when the user omitted a scheme."""
    raw = url.strip()
    if "://" not in raw:
        return "https://" + raw
    return raw


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Return an absolute http(s) URL without a fragment, or None.

    Hosts are lowercased and default ports are dropped. Paths keep their case.
    Query strings are preserved as written.
    """
    candidate = url.strip()
    if not candidate:
        return None
    if base:
        candidate = urljoin(base, candidate)
    candidate, _fragment = urldefrag(candidate)
    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.lower()
    port = parts.port
    default_port = 443 if scheme == "https" else 80
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    path = _collapse_path(parts.path or "/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def _collapse_path(path: str) -> str:
    """Resolve . and .. segments. A trailing slash is preserved."""
    trailing = path.endswith("/")
    kept: list[str] = []
    for piece in path.split("/"):
        if piece in ("", "."):
            continue
        if piece == "..":
            if kept:
                kept.pop()
            continue
        kept.append(piece)
    collapsed = "/" + "/".join(kept)
    if trailing and collapsed != "/":
        collapsed += "/"
    return collapsed


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _site_key(url: str) -> tuple[str, str] | None:
    """Identity used to decide whether a URL belongs to the audited site.

    www and the bare host match. http and https match when both use their
    default ports. An explicit non-default port stays distinct, so a second
    local server is treated as another site.
    """
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    default_port = 443 if parts.scheme == "https" else 80
    if port in (None, default_port):
        return host, "default"
    return host, str(port)


def same_site(url: str, start_url: str, include_subdomains: bool = False) -> bool:
    left = _site_key(url)
    right = _site_key(start_url)
    if left is None or right is None or left[1] != right[1]:
        return False
    if left[0] == right[0]:
        return True
    if not include_subdomains:
        return False
    root = right[0]
    return left[0].endswith("." + root)


class SiteScope:
    """Which URLs belong to the site that the crawl started on."""

    def __init__(self, start_url: str, include_subdomains: bool = False) -> None:
        self.start_url = start_url
        self.include_subdomains = include_subdomains

    def contains(self, url: str) -> bool:
        return same_site(url, self.start_url, self.include_subdomains)


def dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return ordered
