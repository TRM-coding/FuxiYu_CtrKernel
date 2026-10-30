#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 PR 正文的新增、修复、优化栏目；下一步计划不计为交付。

只使用 Python 3 标准库。被校验的正文一律当作数据处理：既不求值其中的
表达式，也不调用 shell。退出码：0 通过；1 校验失败或输入不可用；
2 参数用法错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys

EXIT_OK = 0
EXIT_INVALID = 1

SECTION_NEW = "NEW"
SECTION_FIX = "FIX"
SECTION_ENHANCEMENT = "ENHANCEMENT"
DELIVERY_SECTIONS = (SECTION_NEW, SECTION_FIX, SECTION_ENHANCEMENT)
_OTHER_HEADING = "__other_heading__"

_SECTION_LABELS = {
    SECTION_NEW: "新增内容 | WHAT'S NEW",
    SECTION_FIX: "漏洞修复 | Bug Fixes",
    SECTION_ENHANCEMENT: "优化工作 | Enhancements & Patches",
}

_DELIVERY_HEADING_RE = re.compile(
    r"^(新增内容\s*\|\s*WHAT['’]S\s+NEW|漏洞修复\s*\|\s*Bug\s+Fixes|"
    r"优化工作\s*\|\s*Enhancements\s*&\s*Patches)\s*$",
    re.IGNORECASE,
)
_PLAN_HEADING_RE = re.compile(r"^下一步计划\s*\|\s*Coming\s+Up\s*$", re.IGNORECASE)

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)$")
_NEW_FIX_HEADING_RE = re.compile(
    r"^(NEW|FIX)\s*[:：]?\s*(?:\|\s*(.*))?$", re.IGNORECASE
)
_OPTIONAL_INLINE_RE = re.compile(r"^(?:验证(?:说明|结果)?|通过率)\s*[:：]\s*(.*)$")
_OPTIONAL_BARE_RE = re.compile(r"^(?:验证(?:说明|结果)?|通过率)\s*[:：]?\s*$")
_BULLET_RE = re.compile(r"^\s*[-*+](?:\s+(.*))?\s*$")
_FENCE_OPEN_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")

# 只把“整条就是占位”的文字判为占位，避免误伤包含这些词的正常条目。
_PLACEHOLDER_EXACT = {
    "todo",
    "fixme",
    "tbd",
    "xxx",
    "xx",
    "placeholder",
    "none",
    "n/a",
    "na",
    "null",
    "nil",
    "无",
    "暂无",
    "没有",
    "待填写",
    "待补充",
    "待完善",
    "待定",
    "待办",
    "填写",
    "补充",
    "请填写",
    "请补充",
    "请说明",
    "示例",
    "sample",
    "example",
    "...",
    "…",
}
_PLACEHOLDER_PREFIX_EN = ("todo", "fixme", "tbd")
_PLACEHOLDER_PREFIX_ZH = ("待填写", "待补充", "待完善", "待定", "请填写", "请补充")
_PLACEHOLDER_HINT_WORDS = ("填写", "补充", "说明", "示例", "请")


def preprocess(body):
    """去掉 HTML 注释与围栏代码块，返回剩余行。

    注释和代码块里的文字不构成栏目条目。
    """
    if not body:
        return []
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    kept = []
    in_comment = False
    in_fence = False
    fence_char = ""
    fence_len = 0

    for raw_line in text.split("\n"):
        # 1) 去掉 HTML 注释（可能跨行，也可能与正文同行）
        rest = raw_line
        while True:
            if in_comment:
                idx = rest.find("-->")
                if idx < 0:
                    rest = ""
                    break
                rest = rest[idx + 3 :]
                in_comment = False
                continue
            start = rest.find("<!--")
            if start < 0:
                break
            after = rest[start + 4 :]
            end = after.find("-->")
            if end < 0:
                rest = rest[:start]
                in_comment = True
                break
            rest = rest[:start] + after[end + 3 :]
        if in_comment:
            # 保留注释起始符之前的可见文字，其余当作不存在
            if rest.strip():
                kept.append(rest)
            continue

        # 2) 围栏代码块整体忽略
        if in_fence:
            closer = re.match(
                r"^\s{0,3}(" + re.escape(fence_char) + r"{" + str(fence_len) + r",})\s*$",
                rest,
            )
            if closer:
                in_fence = False
                fence_char = ""
                fence_len = 0
            continue
        opener = _FENCE_OPEN_RE.match(rest)
        if opener:
            in_fence = True
            fence_char = opener.group(1)[0]
            fence_len = len(opener.group(1))
            continue

        kept.append(rest)

    return kept


def _match_section_heading(line):
    """识别栏目标题。

    返回 (栏目, 同行内容)；识别到其他 Markdown 标题时返回 (_OTHER_HEADING, "")，
    不是标题则返回 None。支持普通标题行与 Markdown 标题，`|` 两侧空格不敏感。
    """
    md = _MD_HEADING_RE.match(line)
    has_hash = md is not None
    core = md.group(2).strip() if has_hash else line.strip()
    if not core:
        return None

    if _OPTIONAL_INLINE_RE.match(core):
        return (_OTHER_HEADING, "")
    if _OPTIONAL_BARE_RE.match(core):
        return (_OTHER_HEADING, "")

    delivery = _DELIVERY_HEADING_RE.match(core)
    if delivery:
        label = delivery.group(1).split("|", 1)[0].strip()
        key = {"新增内容": SECTION_NEW, "漏洞修复": SECTION_FIX,
               "优化工作": SECTION_ENHANCEMENT}[label]
        return (key, "")
    if _PLAN_HEADING_RE.match(core):
        return (_OTHER_HEADING, "")

    # 兼容接入期间的旧正文；新模板统一使用中英双语栏目。
    new_fix = _NEW_FIX_HEADING_RE.match(core)
    if new_fix:
        key = new_fix.group(1).upper()
        looks_like_heading = (
            has_hash
            or "|" in core
            or core.upper() in (key, key + ":", key + "：")
        )
        if looks_like_heading:
            return (key, (new_fix.group(2) or "").strip())

    if has_hash:
        return (_OTHER_HEADING, "")
    return None


def is_placeholder(text):
    """判断一段文字是否只是占位，不能充当交付条目。"""
    if text is None:
        return True
    raw = text.strip()
    if not raw:
        return True
    plain = re.sub(r"[*_`~]", "", raw).strip()
    if not plain:
        return True
    compact = re.sub(r"\s+", "", plain)
    if not compact:
        return True
    if re.fullmatch(r"[.\-—–…。、,，;；:：|/\\]+", compact):
        return True
    low = compact.lower()
    if low in _PLACEHOLDER_EXACT:
        return True
    if re.match(r"^(?:todo|fixme|tbd)(?:$|[^a-z0-9])", low):
        return True
    if compact.startswith(_PLACEHOLDER_PREFIX_ZH):
        return True
    if re.fullmatch(r"<[^<>]*>", plain):
        return True
    if re.fullmatch(r"[（(][^（()）]*[)）]", compact) and any(
        word in compact for word in _PLACEHOLDER_HINT_WORDS
    ):
        return True
    if re.fullmatch(r"\[[^\[\]]*\]", compact) and any(
        word in compact for word in _PLACEHOLDER_HINT_WORDS + _PLACEHOLDER_PREFIX_EN
    ):
        return True
    return False


def validate_body(body):
    """校验 PR 正文，返回错误理由列表；空列表表示通过。"""
    if body is None:
        body = ""
    lines = preprocess(body)
    if not any(line.strip() for line in lines):
        return ["PR 正文为空，或只有 HTML 注释 / 代码块，没有可校验内容"]

    present = set()
    items = {key: [] for key in DELIVERY_SECTIONS}
    current = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        heading = _match_section_heading(stripped)
        if heading is not None:
            kind, _ = heading
            if kind in DELIVERY_SECTIONS:
                present.add(kind)
                current = kind
            else:
                current = None
            continue

        if current in DELIVERY_SECTIONS:
            bullet = _BULLET_RE.match(stripped)
            if bullet:
                items[current].append(bullet.group(1) or "")

    errors = []
    if not present:
        errors.append(
            "缺少交付栏目：新增内容 | WHAT'S NEW、漏洞修复 | Bug Fixes、"
            "优化工作 | Enhancements & Patches 至少需要一栏及其真实条目"
        )
    else:
        satisfied = [
            key
            for key in DELIVERY_SECTIONS
            if key in present and any(not is_placeholder(item) for item in items[key])
        ]
        if not satisfied:
            names = "、".join(
                _SECTION_LABELS[key]
                for key in DELIVERY_SECTIONS
                if key in present
            )
            errors.append(
                "栏目 "
                + names
                + " 没有有效条目；-、- ...、- TODO、- 待填写、- 无 等占位不计入"
            )

    return errors


def load_event_body(path):
    """从 GitHub event JSON 读取 pull_request.body。"""
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("event JSON 顶层必须是对象")
    pull_request = data.get("pull_request")
    if not isinstance(pull_request, dict):
        raise ValueError("event JSON 缺少 pull_request 对象，无法校验 PR 正文")
    if "body" not in pull_request:
        raise ValueError("event JSON 的 pull_request 缺少 body 字段")
    body = pull_request["body"]
    if body is None:
        return ""
    if not isinstance(body, str):
        raise ValueError("event JSON 的 pull_request.body 不是字符串")
    return body


def load_body_file(path):
    """从文本文件读取 PR 正文，便于本地验收。"""
    with open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


def _use_utf8_stdio():
    """输出重定向到管道或文件时也使用 UTF-8，避免机器读取中文理由时乱码。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass


def main(argv=None):
    _use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="check_pr.py",
        description="校验 PR 的新增、修复、优化交付条目；下一步计划与验证说明可选。",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--event",
        metavar="PATH",
        help="GitHub event JSON 文件路径，读取 pull_request.body",
    )
    group.add_argument(
        "--body-file",
        metavar="PATH",
        help="PR 正文文本文件路径，便于本地验收",
    )
    args = parser.parse_args(argv)

    if args.event is None and args.body_file is None:
        parser.error("必须提供 --event PATH 或 --body-file PATH 之一")

    try:
        if args.event is not None:
            try:
                body = load_event_body(args.event)
            except json.JSONDecodeError as exc:
                print("错误：event JSON 解析失败（%s）" % exc, file=sys.stderr)
                return EXIT_INVALID
        else:
            body = load_body_file(args.body_file)
    except OSError as exc:
        print("错误：无法读取输入文件（%s）" % exc, file=sys.stderr)
        return EXIT_INVALID
    except ValueError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return EXIT_INVALID

    errors = validate_body(body)
    if errors:
        for error in errors:
            print("错误：%s" % error, file=sys.stderr)
        return EXIT_INVALID

    print("PR 正文校验通过。")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
