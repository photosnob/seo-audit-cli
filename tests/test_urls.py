from seoaudit.urls import normalize_url, same_site


def test_normalize_drops_fragment_and_default_port() -> None:
    assert (
        normalize_url("HTTPS://Example.COM:443/a/../b?q=1#section") == "https://example.com/b?q=1"
    )


def test_normalize_resolves_relative_and_rejects_non_http() -> None:
    assert normalize_url("../b", "https://example.com/a/c") == "https://example.com/b"
    assert normalize_url("mailto:a@example.com") is None
    assert normalize_url("#section", "https://example.com/a") == "https://example.com/a"


def test_same_site_www_scheme_and_port() -> None:
    start = "https://www.example.com/page"
    assert same_site("http://example.com/other", start)
    assert same_site("https://example.com:443/other", start)
    assert not same_site("https://example.com:8443/other", start)
    assert not same_site("https://blog.example.com/", start)
    assert same_site("https://blog.example.com/", start, include_subdomains=True)
    assert not same_site("https://notexample.com/", start, include_subdomains=True)
    assert not same_site("http://127.0.0.1:8000/", "http://127.0.0.1:8001/")
