from seoaudit.parse import parse_html


def test_extracts_on_page_signals() -> None:
    html = """
    <html><head>
      <base href="https://example.com/docs/">
      <title>  Field notes   </title>
      <meta name="description" content="A description of the notes.">
      <meta name="robots" content="index, follow">
      <link rel="canonical" href="notes">
      <link rel="alternate" hreflang="en" href="https://example.com/docs/notes">
      <link rel="alternate" hreflang="english" href="/bad">
      <script type="application/ld+json">{"@type":"Article","headline":"Notes"}</script>
      <script type="application/ld+json">{nope</script>
      <meta property="og:title" content="Notes">
    </head><body>
      <h1>First</h1><h1> </h1>
      <p>Visible words live here.</p>
      <img src="pic.png" alt="A chart">
      <img data-src="lazy.png">
      <a href="next">Next</a>
      <a href="mailto:a@example.com">Mail</a>
      <script>ignore these words</script>
    </body></html>
    """
    doc = parse_html(
        html,
        "https://example.com/docs/notes",
        link_header='<https://example.com/other>; rel="canonical", <https://example.com/docs/notes>; rel="stylesheet"',
        robots_header="max-snippet:50",
    )
    assert doc.title == "Field notes"
    assert doc.meta_description == "A description of the notes."
    assert doc.robots == "index, follow, max-snippet:50"
    assert doc.h1s == ["First"]
    assert doc.h1_empty == 1
    assert doc.canonicals == ["https://example.com/docs/notes", "https://example.com/other"]
    assert doc.hreflang[0].is_absolute is True
    assert doc.hreflang[1].lang == "english"
    assert doc.hreflang[1].url == "https://example.com/bad"
    assert doc.jsonld[0].valid and doc.jsonld[0].types == ["Article"]
    assert doc.jsonld[1].valid is False
    assert doc.og["og:title"] == "Notes"
    assert [image.alt for image in doc.images] == ["A chart", None]
    assert doc.links == ["https://example.com/docs/next"]
    assert doc.word_count == 7


def test_word_count_ignores_script_and_counts_body() -> None:
    html = "<html><head><title>Title words</title></head><body><p>One two</p><script>three four</script></body></html>"
    assert parse_html(html, "https://example.com/").word_count == 2
