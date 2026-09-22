from docstate.core import render

MD = """---
title: T
task_scope: shared
---
# 标题

| a | b |
|---|---|
| 1 | 2 |

- [x] done
- [ ] todo

```mermaid
flowchart LR
  A --> B
```

```python
print("hi")
```

看 [[known]] 和 [[unknown|别名]]，代码里的 `[[not-a-link]]` 不动。
"""


def _resolve(name: str):
    return "known-slug" if name == "known" else None


def test_markdown_features_render():
    body = render.render_markdown_body(MD, _resolve)
    assert "<table>" in body
    assert body.count("task-list-item-checkbox") == 2
    assert '<pre class="mermaid">' in body and "A --&gt; B" in body
    assert 'class="k"' in body or 'class="nb"' in body  # pygments spans
    assert '<a class="wikilink" href="/d/known-slug">known</a>' in body
    assert '<span class="wikilink missing" title="[[unknown]]">别名</span>' in body
    assert "[[not-a-link]]" in body  # inline code is left alone


def test_markdown_page_wrapper_and_task_scope():
    page = render.render_markdown_page(MD, "T", _resolve, eyebrow="DEMO · 2026-09-09", lang="zh-CN")
    assert "DEMO · 2026-09-09" in page
    assert render.BRIDGE_TAG in page
    assert render.BRIDGE_MARK in page and 'src="/static/' not in page  # inline, no request
    assert 'var SCOPE = "shared"' in page
    assert "mermaid.min.js" in page
    assert '<html lang="zh-CN">' in page
    assert "Saved · shared with everyone" in page  # default UI strings unless overridden
    # the body already starts with an h1, so the wrapper must not add another
    assert page.count("<h1") == 1


def test_markdown_wrapper_takes_ui_strings():
    page = render.render_markdown_page("- [ ] x", "T", _resolve, ui={"saved_me": "已保存"})
    assert "已保存" in page and "Saved · shared with everyone" in page


def test_markdown_without_h1_gets_title():
    page = render.render_markdown_page("just text", "自动标题", _resolve)
    assert "<h1>自动标题</h1>" in page
    assert "mermaid.min.js" not in page


def test_prepare_html_injects_bridge_in_head():
    html = "<!doctype html><html><head><title>x</title></head><body><p>hi</p></body></html>"
    out = render.prepare_html(html)
    assert out.index(render.BRIDGE_TAG) < out.index("</head>")
    assert render.prepare_html(out) == out  # idempotent
    no_head = "<body class=a><p>hi</p></body>"
    assert render.prepare_html(no_head).startswith("<body class=a>\n" + render.BRIDGE_TAG)
    assert render.prepare_html("<p>bare</p>").startswith(render.BRIDGE_TAG)
    assert 'src="/static/docbridge.js"' not in out


def test_relative_links_follow_the_repository_layout():
    known = {"dw/zh/01-quickstart.md": "zh-01-quickstart", "decisions/004-x.md": "004-x"}
    src = "\n".join(
        [
            "[a](zh/01-quickstart.md#part)",
            "[b](../decisions/004-x.md)",
            "[c](../server/missing.md)",
            "[d](zh/)",
            "[e](sop)",
            "[f](../scripts/run.sql)",
            "[g](https://example.com/x.md)",
            "[h](#local)",
            "[i](/d/abs)",
            "[j](../../outside.md)",
            "![img](assets/pic.png)",
        ]
    )
    html = render.render_markdown_body(
        src,
        resolve=lambda n: None,
        source_path="dw/README.md",
        resolve_path=known.get,
        repo_url="https://github.com/acme/docs/blob/main/",
    )
    assert 'href="/d/zh-01-quickstart#part"' in html
    assert 'href="/d/004-x"' in html
    assert 'href="https://github.com/acme/docs/blob/main/server/missing.md"' in html
    assert 'href="/c/dw/zh"' in html and 'href="/c/dw/sop"' in html
    assert 'href="https://github.com/acme/docs/blob/main/scripts/run.sql"' in html
    assert 'href="https://example.com/x.md"' in html
    assert 'href="#local"' in html and 'href="/d/abs"' in html
    assert 'href="../../outside.md"' in html  # escapes the repository: left alone
    assert 'src="assets/pic.png"' in html  # images untouched until assets are served
    plain = render.render_markdown_body("[a](zh/01-quickstart.md)", resolve=lambda n: None)
    assert 'href="zh/01-quickstart.md"' in plain  # no source path: nothing rewritten
    bare = render.render_markdown_body(
        "[c](../server/missing.md)",
        resolve=lambda n: None,
        source_path="dw/README.md",
        resolve_path=known.get,
    )
    assert 'href="../server/missing.md"' in bare  # no repository URL configured


def test_extract_text_and_html_meta():
    html = "<html><head><title>报告 &amp; 结论</title><style>p{}</style></head><body><script>1</script><p>第一段 <b>粗</b></p></body></html>"
    assert render.extract_text(html, "html") == "报告 & 结论 第一段 粗"
    assert render.html_title(html) == "报告 & 结论"
    assert render.html_description(html) == "第一段 粗"
    assert render.extract_text("# H\n\n```py\nx\n```\n\n**bold** [l](u)", "md") == "H bold l u"


def test_csp_isolates_documents():
    csp = render.RAW_HEADERS["Content-Security-Policy"]
    assert csp.startswith("sandbox ")
    assert "allow-same-origin" not in csp
    assert "frame-ancestors 'self'" in csp
    assert "connect-src 'none'" in csp


def test_links_written_as_raw_html_are_rewritten_too():
    """A styled call-to-action is raw HTML, so it never reaches link_open; its
    href must still be resolved or it 404s inside the sandboxed frame."""
    known = {"guides/site/tour.html": "tour"}
    src = (
        '<a href="./guides/site/tour.html" style="display:block">看看</a>\n\n'
        '<a href="scripts/run.sql">脚本</a> <a href="/d/already">站内</a> '
        '<a href="https://example.com/x">外部</a>\n\n[markdown](guides/site/tour.html)'
    )
    html = render.render_markdown_body(
        src,
        resolve=lambda n: None,
        source_path="README.md",
        resolve_path=known.get,
        repo_url="https://github.com/acme/docs/blob/main/",
    )
    assert html.count('href="/d/tour"') == 2  # the raw-HTML card and the markdown link
    assert 'href="https://github.com/acme/docs/blob/main/scripts/run.sql"' in html
    assert 'href="/d/already"' in html and 'href="https://example.com/x"' in html
    assert 'style="display:block"' in html  # the rest of the tag is untouched
