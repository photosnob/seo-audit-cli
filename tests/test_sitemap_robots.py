import gzip

from seoaudit.robots import parse_robots
from seoaudit.sitemap import parse_sitemap_xml


def test_sitemap_urlset_index_gzip_and_doctype() -> None:
    urlset = b"""<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
      <url><loc>https://example.com/a</loc></url>
      <url><loc>https://example.com/b</loc><image:image><image:loc>https://example.com/a.jpg</image:loc></image:image></url>
    </urlset>
    """
    parsed = parse_sitemap_xml(urlset)
    assert parsed.error is None
    assert parsed.page_urls == ["https://example.com/a", "https://example.com/b"]
    index = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/one.xml</loc></sitemap>
    </sitemapindex>"""
    parsed = parse_sitemap_xml(gzip.compress(index))
    assert parsed.child_urls == ["https://example.com/one.xml"]
    rejected = parse_sitemap_xml(b"<!DOCTYPE foo [<!ENTITY x 'y'>]><urlset></urlset>")
    assert rejected.error
    broken = parse_sitemap_xml(b"<nope>")
    assert broken.error


def test_robots_disallow_sitemap_and_delay() -> None:
    text = """
    User-agent: *
    Disallow: /private
    Crawl-delay: 2

    Sitemap: https://example.com/sitemap.xml
    """
    robots = parse_robots(text, "https://example.com/robots.txt")
    assert robots.allows("https://example.com/public", "SeoAuditBot/0.1")
    assert not robots.allows("https://example.com/private/secret", "SeoAuditBot/0.1")
    assert robots.sitemaps == ["https://example.com/sitemap.xml"]
    assert robots.parser is not None
    assert robots.parser.crawl_delay("SeoAuditBot/0.1") == 2
