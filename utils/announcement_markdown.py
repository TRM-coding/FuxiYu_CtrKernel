"""公告 Markdown 到邮件 HTML 的渲染。

渲染器只服务公告邮件：关闭原始 HTML、保留单换行、启用基础表格，
链接与图片共用同一允许列表，图片只在正文中降级为转义后的 alt 文本。
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml

_ALLOWED_LINK_PREFIXES = ("http://", "https://", "mailto:")

_WRAPPER_STYLE = (
    "font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; "
    "color: #1f2328;"
)

_HEADING_SIZES = {"h1": 22, "h2": 18, "h3": 16, "h4": 15, "h5": 14, "h6": 14}

_PARAGRAPH_STYLE = "margin: 0 0 12px;"
_LIST_STYLE = "margin: 0 0 12px; padding-left: 24px;"
_LIST_ITEM_STYLE = "margin: 0 0 4px;"
_QUOTE_STYLE = (
    "margin: 0 0 12px; padding-left: 12px; "
    "border-left: 3px solid #d0d7de; color: #57606a;"
)
_TABLE_STYLE = "border-collapse: collapse; width: 100%; margin: 0 0 12px;"
_CELL_STYLE = "border: 1px solid #d0d7de; padding: 6px 8px;"
_HEADER_CELL_STYLE = f"{_CELL_STYLE} background-color: #f6f8fa;"
_CODE_STYLE = (
    "font-family: Consolas, monospace; background-color: #f6f8fa; "
    "padding: 2px 4px;"
)
_PRE_STYLE = (
    "font-family: Consolas, monospace; background-color: #f6f8fa; "
    "padding: 8px; overflow-x: auto;"
)
_LINK_STYLE = "color: #0969da; text-decoration: underline;"


def _validate_link(url: str) -> bool:
    """仅允许公告邮件可用的绝对链接 scheme。"""
    return url.strip().lower().startswith(_ALLOWED_LINK_PREFIXES)


def _render_image(self, tokens, idx, options, env) -> str:
    """图片不生成 img/src，只保留转义后的可见 alt 文本。"""
    return escapeHtml(tokens[idx].content or "")


def _add_style(token, style: str) -> None:
    current = token.attrGet("style")
    token.attrSet("style", f"{current}; {style}" if current else style)


def _apply_email_styles(state) -> None:
    for token in state.tokens:
        token_type = token.type
        if token_type == "heading_open":
            size = _HEADING_SIZES.get(token.tag, 14)
            _add_style(
                token,
                f"font-size: {size}px; font-weight: 600; line-height: 1.3; "
                "margin: 16px 0 8px; color: #1f2328;",
            )
        elif token_type == "paragraph_open":
            _add_style(token, _PARAGRAPH_STYLE)
        elif token_type == "blockquote_open":
            _add_style(token, _QUOTE_STYLE)
        elif token_type in ("bullet_list_open", "ordered_list_open"):
            _add_style(token, _LIST_STYLE)
        elif token_type == "list_item_open":
            _add_style(token, _LIST_ITEM_STYLE)
        elif token_type == "table_open":
            _add_style(token, _TABLE_STYLE)
        elif token_type == "th_open":
            _add_style(token, _HEADER_CELL_STYLE)
        elif token_type == "td_open":
            _add_style(token, _CELL_STYLE)
        elif token_type == "fence":
            _add_style(token, _PRE_STYLE)
        elif token_type == "code_block":
            _add_style(token, _PRE_STYLE)
        elif token_type == "inline":
            for child in token.children or []:
                if child.type == "code_inline":
                    _add_style(child, _CODE_STYLE)
                elif child.type == "link_open":
                    _add_style(child, _LINK_STYLE)


def _build_markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "breaks": True})
    md.enable("table")
    md.validateLink = _validate_link
    md.add_render_rule("image", _render_image)
    md.core.ruler.push("announcement_email_styles", _apply_email_styles)
    return md


_MARKDOWN = _build_markdown()


def render_announcement_html(source: str) -> str:
    """将公告正文渲染为邮件 HTML 片段。"""
    body = _MARKDOWN.render(source or "")
    return f'<div style="{_WRAPPER_STYLE}">{body}</div>'
