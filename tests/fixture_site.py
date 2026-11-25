"""Local fixture sites for tests and the sample report.

The demo site is intentionally full of technical SEO faults. Nothing here is a
crawl of a live website.
"""

from __future__ import annotations

import argparse
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

OriginHandler = Callable[[str], "Response"]


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)


class App:
    def __init__(self) -> None:
        self.routes: dict[str, OriginHandler] = {}

    def handle(self, path: str, origin: str) -> Response:
        handler = self.routes.get(path)
        if handler is None:
            return Response(404, b"missing", "text/plain; charset=utf-8")
        return handler(origin)


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, app: App, port: int) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.app = app
        host, actual = self.server_address[:2]
        self.origin = f"http://{host}:{actual}"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Server

    def do_GET(self) -> None:
        path = urlsplit(self.path).path or "/"
        response = self.server.app.handle(path, self.server.origin)
        body = response.body
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class FixtureServer:
    def __init__(self, app: App, port: int = 0) -> None:
        self.httpd = _Server(app, port)
        self.origin = self.httpd.origin
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)


def fit_title(label: str) -> str:
    text = f"Field notes on {label}"
    if len(text) < 30:
        text += " archive"
    if len(text) < 30:
        text += " entry"
    if not 30 <= len(text) <= 60:
        raise ValueError(f"title {label!r} is {len(text)} chars: {text}")
    return text


def fit_meta(label: str) -> str:
    text = f"Reference notes for the {label} page of the Northwind field archive."
    if len(text) < 70:
        text += " Seasonal context is included."
    if len(text) > 160:
        text = text[:160].rstrip()
    if not 70 <= len(text) <= 160:
        raise ValueError(f"meta {label!r} is {len(text)} chars: {text}")
    return text


def word_block(count: int) -> str:
    vocab = ["soil", "rain", "yield", "market", "field", "season", "note", "sample"]
    return " ".join(vocab[index % len(vocab)] for index in range(count))


SHARED_TITLE = "Shared fixture title for duplicate detection"
SHARED_META = "Shared fixture description used by two pages so duplicate detection has a stable pair to find today."
LONG_TITLE = (
    "Seasonal archive of soil temperature rainfall yield and market prices from Northwind farms"
)
SHORT_META = "Too short."
LONG_META = (
    "This description is deliberately long enough to exceed the usual search snippet. "
    "It keeps going so the audit can flag a meta description that will be truncated in results."
)


def _guard_copy() -> None:
    if not 30 <= len(SHARED_TITLE) <= 60:
        raise RuntimeError(f"SHARED_TITLE length {len(SHARED_TITLE)}")
    if not 70 <= len(SHARED_META) <= 160:
        raise RuntimeError(f"SHARED_META length {len(SHARED_META)}: {SHARED_META}")
    if len(LONG_TITLE) <= 60:
        raise RuntimeError(f"LONG_TITLE length {len(LONG_TITLE)}")
    if len(SHORT_META) >= 70:
        raise RuntimeError("SHORT_META is not short")
    if len(LONG_META) <= 160:
        raise RuntimeError(f"LONG_META length {len(LONG_META)}")


_guard_copy()


def html_page(
    origin: str,
    path: str,
    *,
    title: str | None,
    meta: str | None,
    h1s: list[str] | None,
    canonicals: list[str] | None,
    robots: str | None = None,
    extra_head: str = "",
    body: str = "",
    words: int = 0,
    jsonld: str | None = None,
    og: bool = False,
    image: str | None = None,
) -> str:
    head = ['<meta charset="utf-8">']
    if title is not None:
        head.append(f"<title>{_esc(title)}</title>")
    if meta is not None:
        head.append(f'<meta name="description" content="{_esc(meta)}">')
    if robots:
        head.append(f'<meta name="robots" content="{_esc(robots)}">')
    if canonicals:
        for href in canonicals:
            head.append(f'<link rel="canonical" href="{_esc(href)}">')
    if og and title and meta:
        image_url = f"{origin}/og.png"
        head.append(f'<meta property="og:title" content="{_esc(title)}">')
        head.append(f'<meta property="og:description" content="{_esc(meta)}">')
        head.append(f'<meta property="og:image" content="{_esc(image_url)}">')
        head.append(f'<meta property="og:url" content="{_esc(origin + path)}">')
    if jsonld is not None:
        safe = jsonld.replace("<", "\\u003c")
        head.append(f'<script type="application/ld+json">{safe}</script>')
    if extra_head:
        head.append(extra_head)
    blocks = []
    if h1s is not None:
        for heading in h1s:
            blocks.append(f"<h1>{_esc(heading)}</h1>")
    if words:
        blocks.append(f"<p>{word_block(words)}</p>")
    if image is not None:
        blocks.append(image)
    if body:
        blocks.append(body)
    return (
        "<!DOCTYPE html><html><head>"
        + "".join(head)
        + "</head><body>"
        + "".join(blocks)
        + "</body></html>"
    )


def complete_page(
    origin: str,
    path: str,
    *,
    words: int = 320,
    extra_head: str = "",
    body: str = "",
    image: str | None = '<img src="/notebook.png" alt="Field notebook">',
    **overrides: object,
) -> str:
    label = path.strip("/").replace("/", " ") or "home"
    title = overrides.pop("title", fit_title(label))
    meta = overrides.pop("meta", fit_meta(label))
    h1 = overrides.pop("h1", f"Notes on {label}")
    canonical = overrides.pop("canonical", origin + path)
    include_json = overrides.pop("jsonld", True)
    include_og = overrides.pop("og", True)
    if overrides:
        raise TypeError(f"Unknown complete_page arguments: {sorted(overrides)}")
    payload = None
    if include_json:
        payload = json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": title,
                "url": origin + path,
            }
        )
    canonicals = None if canonical is None else [str(canonical)]
    return html_page(
        origin,
        path,
        title=None if title is None else str(title),
        meta=None if meta is None else str(meta),
        h1s=None if h1 is None else [str(h1)],
        canonicals=canonicals,
        extra_head=extra_head,
        body=body,
        words=words,
        jsonld=payload,
        og=bool(include_og),
        image=image or None,
    )


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _html(
    path: str, builder: Callable[[str], str], headers: dict[str, str] | None = None
) -> OriginHandler:
    def handle(origin: str) -> Response:
        body = builder(origin).encode("utf-8")
        return Response(200, body, headers=dict(headers or {}))

    return handle


def _text(status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> OriginHandler:
    payload = body.encode("utf-8")
    return lambda origin: Response(status, payload, content_type)


def _redirect(status: int, location: str) -> OriginHandler:
    def handle(origin: str) -> Response:
        target = location if location.startswith("http") else origin + location
        return Response(status, b"", "text/plain", {"Location": target})

    return handle


def build_external_app() -> App:
    app = App()
    app.routes["/ok"] = _text(200, "ok")
    app.routes["/missing"] = _text(404, "missing")
    return app


def build_clean_app() -> App:
    app = App()

    def page(origin: str) -> str:
        return complete_page(origin, "/", words=320)

    def robots(origin: str) -> Response:
        body = f"User-agent: *\nDisallow:\n\nSitemap: {origin}/sitemap.xml\n"
        return Response(200, body.encode(), "text/plain; charset=utf-8")

    def sitemap(origin: str) -> Response:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{origin}/</loc></url>"
            "</urlset>"
        )
        return Response(200, xml.encode(), "application/xml")

    app.routes["/"] = _html("/", page)
    app.routes["/robots.txt"] = robots
    app.routes["/sitemap.xml"] = sitemap
    return app


def build_demo_app(external_origin: str) -> App:
    app = App()
    sitemap_paths = [
        "/",
        "/about",
        "/sitemap-only",
        "/guides",
        "/guides/start",
        "/guides/mid",
        "/guides/deep",
        "/noindex",
        "/hreflang",
        "/es",
        "/fr",
        "/missing-page",
        "/redirect",
        "/private/secret",
    ]

    def add(path: str, handler: OriginHandler) -> None:
        app.routes[path] = handler

    def page(
        path: str, builder: Callable[[str], str], headers: dict[str, str] | None = None
    ) -> None:
        add(path, _html(path, builder, headers))

    def robots(origin: str) -> Response:
        body = f"User-agent: *\nDisallow: /private\n\nSitemap: {origin}/sitemap.xml\n"
        return Response(200, body.encode(), "text/plain; charset=utf-8")

    def sitemap_index(origin: str) -> Response:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<sitemap><loc>{origin}/sitemaps/pages.xml</loc></sitemap>"
            "</sitemapindex>"
        )
        return Response(200, xml.encode(), "application/xml")

    def sitemap_pages(origin: str) -> Response:
        locs = "".join(f"<url><loc>{origin}{path}</loc></url>" for path in sitemap_paths)
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{locs}</urlset>"
        )
        return Response(200, xml.encode(), "application/xml")

    links = [
        "/about",
        "/thin",
        "/orphan",
        "/dup-a",
        "/dup-b",
        "/title-long",
        "/meta-short",
        "/meta-long",
        "/missing-canonical",
        "/bad-canonical",
        "/conflicting-canonical",
        "/header-canonical",
        "/noindex",
        "/x-robots",
        "/hreflang",
        "/no-self-hreflang",
        "/images",
        "/jsonld-bad",
        "/jsonld-empty",
        "/heavy",
        "/multi-h1",
        "/empty-h1",
        "/redirect",
        "/redirect-chain",
        "/redirect-long",
        "/loop-a",
        "/chain/0",
        "/bad-redirect",
        "/redirect-out",
        "/missing-page",
        "/server-error",
        "/limited",
        "/guides",
        "/private/secret",
        f"{external_origin}/ok",
        f"{external_origin}/missing",
    ]

    def home(origin: str) -> str:
        items = "".join(f'<li><a href="{_esc(href)}">{_esc(href)}</a></li>' for href in links)
        return html_page(
            origin,
            "/",
            title="Notes",
            meta=fit_meta("home"),
            h1s=["Northwind field notes"],
            canonicals=[origin + "/"],
            body=f"<ul>{items}</ul>",
            words=320,
            jsonld=json.dumps(
                {
                    "@context": "https://schema.org",
                    "@type": "WebSite",
                    "name": "Northwind",
                    "url": origin + "/",
                }
            ),
            og=True,
            image='<img src="/notebook.png" alt="Field notebook">',
        )

    page("/", home)
    page("/about", lambda origin: complete_page(origin, "/about", words=60))
    page("/sitemap-only", lambda origin: complete_page(origin, "/sitemap-only"))
    page("/orphan", lambda origin: complete_page(origin, "/orphan"))
    for guide in ("/guides", "/guides/start", "/guides/mid", "/guides/deep"):
        nxt = {
            "/guides": "/guides/start",
            "/guides/start": "/guides/mid",
            "/guides/mid": "/guides/deep",
            "/guides/deep": "",
        }[guide]

        def builder(origin: str, path: str = guide, target: str = nxt) -> str:
            body = f'<p><a href="{target}">Next</a></p>' if target else ""
            return complete_page(origin, path, body=body)

        page(guide, builder)
    page(
        "/thin",
        lambda origin: html_page(
            origin,
            "/thin",
            title=None,
            meta=None,
            h1s=None,
            canonicals=None,
            body="<p>Too little text.</p>",
        ),
    )
    for dup in ("/dup-a", "/dup-b"):
        page(
            dup,
            lambda origin, path=dup: complete_page(
                origin, path, title=SHARED_TITLE, meta=SHARED_META, words=320
            ),
        )
    page("/title-long", lambda origin: complete_page(origin, "/title-long", title=LONG_TITLE))
    page("/meta-short", lambda origin: complete_page(origin, "/meta-short", meta=SHORT_META))
    page("/meta-long", lambda origin: complete_page(origin, "/meta-long", meta=LONG_META))
    page(
        "/missing-canonical",
        lambda origin: complete_page(origin, "/missing-canonical", canonical=None),
    )
    page(
        "/bad-canonical",
        lambda origin: complete_page(origin, "/bad-canonical", canonical=origin + "/missing-page"),
    )
    page(
        "/conflicting-canonical",
        lambda origin: html_page(
            origin,
            "/conflicting-canonical",
            title=fit_title("conflicting canonical"),
            meta=fit_meta("conflicting canonical"),
            h1s=["Two canonicals"],
            canonicals=[origin + "/conflicting-canonical", origin + "/about"],
            words=320,
            jsonld=json.dumps(
                {"@context": "https://schema.org", "@type": "WebPage", "name": "Two"}
            ),
            og=True,
            image='<img src="/notebook.png" alt="Field notebook">',
        ),
    )

    def header_canonical(origin: str) -> Response:
        body = complete_page(origin, "/header-canonical").encode()
        return Response(200, body, headers={"Link": f'<{origin}/about>; rel="canonical"'})

    add("/header-canonical", header_canonical)
    page(
        "/noindex",
        lambda origin: complete_page(origin, "/noindex"),
    )
    # noindex meta is not part of complete_page; rebuild with robots.
    page(
        "/noindex",
        lambda origin: html_page(
            origin,
            "/noindex",
            title=fit_title("noindex page"),
            meta=fit_meta("noindex page"),
            h1s=["Hidden notes"],
            canonicals=[origin + "/noindex"],
            robots="noindex, nofollow",
            words=320,
            jsonld=json.dumps(
                {"@context": "https://schema.org", "@type": "WebPage", "name": "Hidden"}
            ),
            og=True,
            image='<img src="/notebook.png" alt="Field notebook">',
        ),
    )

    def x_robots(origin: str) -> Response:
        body = complete_page(origin, "/x-robots").encode()
        return Response(200, body, headers={"X-Robots-Tag": "noindex"})

    add("/x-robots", x_robots)
    page(
        "/hreflang",
        lambda origin: complete_page(
            origin,
            "/hreflang",
            extra_head=(
                f'<link rel="alternate" hreflang="en" href="{origin}/hreflang">'
                '<link rel="alternate" hreflang="en-us" href="/hreflang">'
                f'<link rel="alternate" hreflang="es" href="{origin}/es">'
                f'<link rel="alternate" hreflang="fr" href="{origin}/fr">'
                f'<link rel="alternate" hreflang="english" href="{origin}/fr">'
                f'<link rel="alternate" hreflang="de" href="{origin}/de-missing">'
            ),
        ),
    )
    page(
        "/es",
        lambda origin: complete_page(
            origin,
            "/es",
            extra_head=(
                f'<link rel="alternate" hreflang="es" href="{origin}/es">'
                f'<link rel="alternate" hreflang="en" href="{origin}/hreflang">'
            ),
        ),
    )
    page(
        "/fr",
        lambda origin: complete_page(
            origin,
            "/fr",
            extra_head=f'<link rel="alternate" hreflang="fr" href="{origin}/fr">',
        ),
    )
    page(
        "/no-self-hreflang",
        lambda origin: complete_page(
            origin,
            "/no-self-hreflang",
            extra_head=(
                f'<link rel="alternate" hreflang="en" href="{origin}/es">'
                f'<link rel="alternate" hreflang="es" href="{origin}/es">'
            ),
        ),
    )
    page(
        "/images",
        lambda origin: complete_page(
            origin,
            "/images",
            image="",
            body='<img src="/missing-alt.png"><img src="/decorative.png" alt="">',
        ),
    )
    page(
        "/jsonld-bad",
        lambda origin: html_page(
            origin,
            "/jsonld-bad",
            title=fit_title("jsonld bad"),
            meta=fit_meta("jsonld bad"),
            h1s=["Broken structured data"],
            canonicals=[origin + "/jsonld-bad"],
            words=320,
            jsonld="{not-json",
            og=True,
            image='<img src="/notebook.png" alt="Field notebook">',
        ),
    )
    page(
        "/jsonld-empty",
        lambda origin: html_page(
            origin,
            "/jsonld-empty",
            title=fit_title("jsonld empty"),
            meta=fit_meta("jsonld empty"),
            h1s=["Empty structured data"],
            canonicals=[origin + "/jsonld-empty"],
            words=320,
            jsonld="{}",
            og=True,
            image='<img src="/notebook.png" alt="Field notebook">',
        ),
    )
    page("/heavy", _heavy_page)
    page(
        "/multi-h1",
        lambda origin: html_page(
            origin,
            "/multi-h1",
            title=fit_title("multi h1"),
            meta=fit_meta("multi h1"),
            h1s=["First heading", "Second heading"],
            canonicals=[origin + "/multi-h1"],
            words=320,
            jsonld=json.dumps(
                {"@context": "https://schema.org", "@type": "WebPage", "name": "Multi"}
            ),
            og=True,
            image='<img src="/notebook.png" alt="Field notebook">',
        ),
    )
    page(
        "/empty-h1",
        lambda origin: html_page(
            origin,
            "/empty-h1",
            title=fit_title("empty h1"),
            meta=fit_meta("empty h1"),
            h1s=[""],
            canonicals=[origin + "/empty-h1"],
            words=320,
            jsonld=json.dumps(
                {"@context": "https://schema.org", "@type": "WebPage", "name": "Empty"}
            ),
            og=True,
            image='<img src="/notebook.png" alt="Field notebook">',
        ),
    )
    page("/private/secret", lambda origin: complete_page(origin, "/private/secret"))
    add("/redirect", _redirect(301, "/about"))
    add("/redirect-chain", _redirect(301, "/mid"))
    add("/mid", _redirect(302, "/about"))
    add("/redirect-long", _redirect(301, "/long/1"))
    add("/long/1", _redirect(302, "/long/2"))
    add("/long/2", _redirect(302, "/about"))
    add("/loop-a", _redirect(301, "/loop-b"))
    add("/loop-b", _redirect(301, "/loop-a"))
    for index in range(12):
        add(f"/chain/{index}", _redirect(301, f"/chain/{index + 1}"))
    add("/bad-redirect", lambda origin: Response(302, b"", "text/plain"))
    add("/redirect-out", _redirect(302, external_origin + "/ok"))
    add("/missing-page", _text(404, "missing"))
    add("/server-error", _text(500, "error"))
    add("/limited", _text(429, "slow down"))
    add("/robots.txt", robots)
    add("/sitemap.xml", sitemap_index)
    add("/sitemaps/pages.xml", sitemap_pages)
    return app


_HEAVY: str | None = None


def _heavy_page(origin: str) -> str:
    global _HEAVY
    if _HEAVY is None:
        chunk = "<p>" + word_block(80) + "</p>"
        parts = ["<div>"]
        while sum(len(part) for part in parts) < 520_000:
            parts.append(chunk)
        parts.append("</div>")
        _HEAVY = "".join(parts)
    return complete_page(origin, "/heavy", body=_HEAVY)


def build_robots_down_app() -> App:
    app = App()
    app.routes["/robots.txt"] = _text(503, "unavailable")
    app.routes["/"] = _html("/", lambda origin: complete_page(origin, "/"))
    app.routes["/sitemap.xml"] = _text(404, "missing")
    return app


def build_bad_sitemap_app() -> App:
    app = App()

    def robots(origin: str) -> Response:
        body = f"Sitemap: {origin}/sitemap.xml\n"
        return Response(200, body.encode(), "text/plain; charset=utf-8")

    app.routes["/robots.txt"] = robots
    app.routes["/sitemap.xml"] = _text(200, "<not-xml>", "application/xml")
    app.routes["/"] = _html("/", lambda origin: complete_page(origin, "/"))
    return app


def build_slow_app() -> App:
    import time

    def slow(origin: str) -> Response:
        time.sleep(1.0)
        return Response(200, b"late", "text/plain")

    app = App()
    app.routes["/robots.txt"] = _text(404, "missing")
    app.routes["/"] = slow
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the seoaudit fixture site.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--external-port", type=int, default=8766)
    args = parser.parse_args()
    external = FixtureServer(build_external_app(), args.external_port)
    demo = FixtureServer(build_demo_app(external.origin), args.port)
    print(f"Fixture site: {demo.origin}/", flush=True)
    print(f"External fixture: {external.origin}/", flush=True)
    print("This server is a local fixture full of intentional SEO faults.", flush=True)
    try:
        demo.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        demo.close()
        external.close()


if __name__ == "__main__":
    main()
