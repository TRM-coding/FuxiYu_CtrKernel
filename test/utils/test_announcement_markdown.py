"""公告 Markdown 渲染的安全与结构测试。"""

import inspect
from html.parser import HTMLParser

from ...utils.announcement_markdown import render_announcement_html


class _HtmlProbe(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self.data: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.data.append(data)


def _parse(source: str) -> _HtmlProbe:
    probe = _HtmlProbe()
    probe.feed(source)
    probe.close()
    return probe


def _tag_names(probe: _HtmlProbe) -> list[str]:
    return [tag for tag, _ in probe.tags]


def _text(probe: _HtmlProbe) -> str:
    return "".join(probe.data)


def _assert_styles_are_inline_and_local(probe: _HtmlProbe) -> None:
    for _, attrs in probe.tags:
        style = attrs.get("style", "").lower()
        assert "url(" not in style
        assert "@import" not in style


def test_render_basic_markdown_structures():
    html = render_announcement_html(
        "# H1\n\n## H2\n\n- a\n- b\n\n1. one\n\n> quote\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
        "[link](https://example.com)\n\n"
        "`inline <b>&`\n\n"
        "```\nfence <script>x</script>\n```\n"
    )
    probe = _parse(html)
    tags = _tag_names(probe)

    for name in (
        "div", "h1", "h2", "p", "ul", "ol", "li", "blockquote",
        "table", "thead", "tbody", "tr", "th", "td", "a", "code", "pre",
    ):
        assert name in tags, name

    for name in ("h1", "h2", "p", "ul", "ol", "li", "blockquote", "table", "th", "td", "a", "code"):
        assert any(tag == name and "style" in attrs for tag, attrs in probe.tags), name

    assert not {"style", "link", "script"} & set(tags)
    _assert_styles_are_inline_and_local(probe)
    assert "inline <b>&" in _text(probe)
    assert "fence <script>x</script>" in _text(probe)


def test_render_escapes_raw_html_and_code():
    html = render_announcement_html(
        'raw <script>alert(1)</script> and <b>bold</b> and '
        '<img src="https://evil.example/x.png">\n\n'
        "`inline <b>&`\n\n"
        "```\nfence <script>alert(2)</script>\n```\n"
    )
    probe = _parse(html)
    tags = _tag_names(probe)
    text = _text(probe)

    assert "script" not in tags
    assert "b" not in tags
    assert "img" not in tags
    assert "<script>alert(1)</script>" in text
    assert "<b>bold</b>" in text
    assert '<img src="https://evil.example/x.png">' in text
    assert "inline <b>&" in text
    assert "<script>alert(2)</script>" in text


def test_render_allows_only_safe_links():
    html = render_announcement_html(
        "[https](https://example.com/a) "
        "[mail](mailto:user@example.com) "
        "[upper](HTTPS://Example.com/UP) "
        "[query](https://example.com/?a=1&b=2) "
        "[rel](relative) "
        "[proto](//evil.example) "
        "[js](javascript:alert(1)) "
        "[data](data:text/html,hi) "
        "[file](file:///etc/passwd)"
    )
    probe = _parse(html)
    hrefs = [attrs["href"] for tag, attrs in probe.tags if tag == "a"]
    text = _text(probe)

    assert len(hrefs) == 4
    assert all(href.lower().startswith(("http://", "https://", "mailto:")) for href in hrefs)
    for literal in (
        "[rel](relative)",
        "[proto](//evil.example)",
        "[js](javascript:alert(1))",
        "[data](data:text/html,hi)",
        "[file](file:///etc/passwd)",
    ):
        assert literal in text
    assert "&amp;" in html


def test_render_suppresses_images_without_resource_requests():
    html = render_announcement_html(
        "![ok](https://img.example/x.png)\n\n"
        '![alt <b> & "q"](https://img.example/y.png)\n\n'
        "![rel](relative)\n\n"
        "![proto](//evil.example/z.png)\n\n"
        "![js](javascript:alert(1))\n\n"
        "![data](data:image/png;base64,AAAA)\n\n"
        "![file](file:///etc/passwd)\n\n"
        'raw <div style="background:url(https://evil.example/bg.png)">x</div>\n\n'
        '`url(https://evil.example/a.png) @import src="x"`\n\n'
        "```\n@import url(https://evil.example/a.css);\n```\n"
    )
    probe = _parse(html)
    tags = _tag_names(probe)
    text = _text(probe)

    assert not {"img", "script", "style", "link", "a"} & set(tags)
    assert not any("src" in attrs for _, attrs in probe.tags)
    assert "b" not in tags
    assert "ok" in text
    assert 'alt <b> & "q"' in text
    assert "&lt;b&gt;" in html
    assert "&quot;" in html
    assert "relative" in text
    assert "//evil.example/z.png" in text
    assert "javascript:alert(1)" in text
    assert "url(https://evil.example/bg.png)" in text
    assert "url(https://evil.example/a.png)" in text
    assert "@import" in text
    _assert_styles_are_inline_and_local(probe)


def test_render_preserves_single_newlines():
    html = render_announcement_html("第一行\n第二行\n\n第三行")
    probe = _parse(html)
    text = _text(probe)

    assert "br" in _tag_names(probe)
    for line in ("第一行", "第二行", "第三行"):
        assert line in text
    assert list(inspect.signature(render_announcement_html).parameters) == ["source"]
