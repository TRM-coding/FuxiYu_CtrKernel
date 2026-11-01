#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_pr.py 的单元测试。

运行：python -m unittest discover -s scripts/ci/tests -p test_check_pr.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import textwrap
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_CI_DIR = os.path.dirname(_TESTS_DIR)
_REPO_ROOT = os.path.dirname(os.path.dirname(_CI_DIR))
if _CI_DIR not in sys.path:
    sys.path.insert(0, _CI_DIR)

import check_pr  # noqa: E402

_TEMPLATE_PATH = os.path.join(_REPO_ROOT, ".github", "pull_request_template.md")


def _body(text):
    return textwrap.dedent(text).strip("\n") + "\n"


class ValidateBodyTests(unittest.TestCase):
    def test_node_pr_four_columns(self):
        self.assert_valid("### 新增内容 | WHAT'S NEW\n- 增加采集端点\n"
                          "### 漏洞修复 | Bug Fixes\n- 修复失败返回\n"
                          "### 优化工作 | Enhancements & Patches\n- 整理规格\n"
                          "### 下一步计划 | Coming Up\n- 增加后续采集指标\n")

    def test_enhancement_only_is_delivery(self):
        self.assert_valid("### 优化工作 | Enhancements & Patches\n- 重组现有规格目录\n")

    def test_plan_only_is_not_delivery(self):
        self.assert_invalid("### 下一步计划 | Coming Up\n- 修复容器生命周期\n")

    def test_plan_items_do_not_satisfy_empty_delivery(self):
        self.assert_invalid("### 新增内容 | WHAT'S NEW\n- 无\n"
                            "### 下一步计划 | Coming Up\n- 新增完整功能\n")

    def test_bare_plan_heading_stops_delivery(self):
        self.assert_invalid("新增内容 | WHAT'S NEW\n- TODO\n"
                            "下一步计划 | Coming Up\n- 未来实现身份功能\n")

    def test_bilingual_case_and_spacing(self):
        self.assert_valid("### 新增内容|what’s new\n- 增加运行指标\n")
        self.assert_valid("漏洞修复 | BUG FIXES\n- 修复路径错误\n")

    def test_bilingual_fenced_delivery_does_not_count(self):
        self.assert_invalid("### 优化工作 | Enhancements & Patches\n"
                            "```markdown\n- 优化缓存\n```\n")

    def assert_valid(self, body):
        errors = check_pr.validate_body(body)
        self.assertEqual(errors, [], "期望校验通过，实际错误：%s" % errors)

    def assert_invalid(self, body, keyword=None):
        errors = check_pr.validate_body(body)
        self.assertTrue(errors, "期望校验失败，但实际通过了")
        if keyword is not None:
            self.assertTrue(
                any(keyword in error for error in errors),
                "错误理由未包含 %r：%s" % (keyword, errors),
            )

    def _run(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_pr.main(args)
        return code, out.getvalue(), err.getvalue()

    # ---- 有效结构 -------------------------------------------------------

    def test_new_only_is_valid(self):
        self.assert_valid(
            _body(
                """
                ## NEW | 新增内容
                - 新增 PR 正文校验脚本

                验证：已运行 python -m unittest，全部通过。
                """
            )
        )

    def test_fix_only_is_valid(self):
        self.assert_valid(
            _body(
                """
                ## FIX | 修复漏洞
                - 修复 Windows 下脚本路径拼接错误

                验证：已运行 python -m unittest，全部通过。
                """
            )
        )

    def test_both_columns_are_valid(self):
        self.assert_valid(
            _body(
                """
                ## NEW | 新增内容
                - 新增 CI 检查入口

                ## FIX | 修复漏洞
                - 修复缓存键缺失的问题

                验证：已运行 python -m unittest，全部通过。
                """
            )
        )

    def test_empty_column_with_wu_is_allowed(self):
        self.assert_valid(
            _body(
                """
                ## NEW | 新增内容
                - 无

                ## FIX | 修复漏洞
                - 修复 CI 缓存未命中导致重复下载的问题

                验证：已运行 python -m unittest，全部通过。
                """
            )
        )

    def test_not_executed_with_reason_is_valid(self):
        self.assert_valid(
            _body(
                """
                ## FIX | 修复漏洞
                - 修复文档中的失效链接

                验证：未执行，原因：仅文档改动，本地无对应运行环境；合入前由 CI 覆盖。
                """
            )
        )

    def test_multiline_verification_with_code_supplement_is_valid(self):
        self.assert_valid(
            _body(
                """
                NEW|新增内容
                - 新增功能 A

                FIX | 修复漏洞
                - 修复功能 B 的空指针

                验证：
                第一步：运行下列命令。
                ```bash
                python -m unittest discover -s scripts/ci/tests -p test_check_pr.py
                ```
                第二步：退出码为 0，全部用例通过。
                """
            )
        )

    def test_heading_styles_and_pipe_spacing(self):
        cases = [
            ("## NEW | 新增内容", "## 验证：已运行 python -m unittest，全部通过。"),
            ("NEW|新增内容", "验证: 已运行 python -m unittest，全部通过。"),
            ("### NEW|新增内容", "### 验证：已运行 python -m unittest，全部通过。"),
            ("NEW | 新增内容", "验证：已运行 python -m unittest，全部通过。"),
        ]
        for heading, verify in cases:
            with self.subTest(heading=heading):
                body = "\n".join([heading, "- 新增功能 A", "", verify]) + "\n"
                self.assert_valid(body)

    def test_extra_columns_do_not_break_validation(self):
        self.assert_valid(
            _body(
                """
                ## 影响
                - 只影响 CI 脚本

                ## NEW | 新增内容
                - 新增功能 A

                ## 验证：
                已运行 python -m unittest，全部通过。
                """
            )
        )

    # ---- 失败结构 -------------------------------------------------------

    def test_empty_or_blank_body_fails(self):
        for body in ("", "   \n\n  \t\n", None):
            with self.subTest(body=body):
                self.assert_invalid(body or "", keyword="正文")

    def test_comment_only_body_fails(self):
        self.assert_invalid(
            _body(
                """
                <!--
                ## NEW | 新增内容
                - 注释里的伪造条目

                验证：注释里的伪造说明
                -->
                """
            ),
            keyword="正文",
        )

    def test_commented_items_do_not_satisfy_a_column(self):
        self.assert_invalid(
            _body(
                """
                ## NEW | 新增内容
                <!-- - 注释里的伪造条目 -->

                验证：已运行 python -m unittest，全部通过。
                """
            )
        )

    def test_fenced_items_do_not_satisfy_a_column(self):
        self.assert_invalid(
            _body(
                """
                ## NEW | 新增内容
                ```markdown
                - 围栏里的伪造条目
                ```

                验证：已运行 python -m unittest，全部通过。
                """
            )
        )

    def test_fenced_copy_of_a_whole_pr_fails(self):
        self.assert_invalid(
            _body(
                """
                ```markdown
                ## NEW | 新增内容
                - 围栏里的伪造条目

                验证：围栏里的伪造说明
                ```
                """
            ),
            keyword="正文",
        )

    def test_placeholder_items_are_rejected(self):
        placeholders = [
            "-",
            "- ...",
            "- TODO",
            "- 待填写",
            "- <在此填写>",
            "- 无",
            "- （请填写）",
        ]
        for bullet in placeholders:
            with self.subTest(bullet=bullet):
                body = (
                    "\n".join(
                        [
                            "## NEW | 新增内容",
                            bullet,
                            "",
                            "验证：已运行 python -m unittest，全部通过。",
                        ]
                    )
                    + "\n"
                )
                self.assert_invalid(body)

    def test_only_wu_in_every_column_fails(self):
        self.assert_invalid(
            _body(
                """
                ## NEW | 新增内容
                - 无

                ## FIX | 修复漏洞
                - 无

                验证：已运行 python -m unittest，全部通过。
                """
            )
        )

    def test_missing_verification_is_valid(self):
        self.assert_valid(
            _body(
                """
                ## NEW | 新增内容
                - 新增功能 A
                """
            )
        )

    def test_optional_verification_with_only_code_block_is_valid(self):
        self.assert_valid(
            _body(
                """
                ## NEW | 新增内容
                - 新增功能 A

                验证：
                ```bash
                python -m unittest discover -s scripts/ci/tests -p test_check_pr.py
                ```
                """
            )
        )

    def test_optional_verification_with_only_html_comment_is_valid(self):
        self.assert_valid(
            _body(
                """
                ## NEW | 新增内容
                - 新增功能 A

                验证：
                <!-- 已在本地运行 python -m unittest，全部通过 -->
                """
            )
        )

    def test_new_or_fix_needs_no_suffix(self):
        for heading in ("NEW | 新增内容", "FIX | 修复漏洞"):
            with self.subTest(heading=heading):
                self.assert_valid(heading + "\n- 更新了对应的规格\n")

    def test_optional_verification_placeholder_is_not_required(self):
        self.assert_valid("FIX | 修复漏洞\n- 修正字段定义\n\n验证：待填写\n")

    def test_verification_bullet_cannot_replace_delivery_item(self):
        self.assert_invalid("NEW | 新增内容\n- TODO\n\n验证：\n- 测试全部通过\n")

    def test_pass_rate_bullet_cannot_replace_delivery_item(self):
        self.assert_invalid("NEW | 新增内容\n- TODO\n\n通过率：\n- 100%\n")

    # ---- CLI 与 event 输入 ---------------------------------------------

    def test_event_metadata_with_quotes_and_backticks_stays_data(self):
        body = _body(
            """
            ## NEW | 新增内容
            - 修复 `__import__("os").system("echo pwned")` 的展示转义

            验证：已运行 `python -m unittest`，输出中的 "引号" 与 `反引号` 均正常显示。
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            event_path = os.path.join(tmp, "event.json")
            with open(event_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {"pull_request": {"number": 1, "body": body}},
                    handle,
                    ensure_ascii=False,
                )
            code, out, err = self._run(["--event", event_path])
        self.assertEqual(code, 0, err)
        self.assertIn("通过", out)

    def test_event_body_only_inside_fence_fails(self):
        body = "```text\nrm -rf /\n```\n"
        with tempfile.TemporaryDirectory() as tmp:
            event_path = os.path.join(tmp, "event.json")
            with open(event_path, "w", encoding="utf-8") as handle:
                json.dump({"pull_request": {"body": body}}, handle, ensure_ascii=False)
            code, out, err = self._run(["--event", event_path])
        self.assertEqual(code, 1)
        self.assertIn("错误", err)

    def test_event_without_pull_request_reports_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            event_path = os.path.join(tmp, "event.json")
            with open(event_path, "w", encoding="utf-8") as handle:
                json.dump({"action": "opened"}, handle)
            code, out, err = self._run(["--event", event_path])
        self.assertEqual(code, 1)
        self.assertIn("pull_request", err)

    def test_event_without_body_field_reports_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            event_path = os.path.join(tmp, "event.json")
            with open(event_path, "w", encoding="utf-8") as handle:
                json.dump({"pull_request": {"number": 1}}, handle)
            code, out, err = self._run(["--event", event_path])
        self.assertEqual(code, 1)
        self.assertIn("body", err)

    def test_invalid_event_json_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            event_path = os.path.join(tmp, "event.json")
            with open(event_path, "w", encoding="utf-8") as handle:
                handle.write("this is not json")
            code, out, err = self._run(["--event", event_path])
        self.assertEqual(code, 1)
        self.assertIn("JSON", err)

    def test_body_file_option_validates_local_pr_body(self):
        good = _body(
            """
            ## NEW | 新增内容
            - 新增功能 A

            """
        )
        bad = _body(
            """
            ## NEW | 新增内容
            - TODO

            验证：待填写
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            good_path = os.path.join(tmp, "good.md")
            bad_path = os.path.join(tmp, "bad.md")
            with open(good_path, "w", encoding="utf-8") as handle:
                handle.write(good)
            with open(bad_path, "w", encoding="utf-8") as handle:
                handle.write(bad)
            good_code, out, err = self._run(["--body-file", good_path])
            bad_code, bad_out, bad_err = self._run(["--body-file", bad_path])
        self.assertEqual(good_code, 0, err)
        self.assertEqual(bad_code, 1)
        self.assertIn("错误", bad_err)

    def test_cli_requires_exactly_one_input(self):
        for args in ([], ["--event", "a.json", "--body-file", "b.md"]):
            with self.subTest(args=args):
                with self.assertRaises(SystemExit) as raised:
                    with contextlib.redirect_stderr(io.StringIO()):
                        check_pr.main(args)
                self.assertNotEqual(raised.exception.code, 0)

    def test_missing_input_file_fails_with_chinese_reason(self):
        missing = os.path.join(tempfile.gettempdir(), "check_pr_missing_event.json")
        code, out, err = self._run(["--event", missing])
        self.assertEqual(code, 1)
        self.assertIn("错误", err)

    # ---- 模板与实现约束 -------------------------------------------------

    @unittest.skipUnless(os.path.exists(_TEMPLATE_PATH), "模板文件不存在")
    def test_template_placeholders_cannot_pass_validation(self):
        with open(_TEMPLATE_PATH, encoding="utf-8") as handle:
            text = handle.read()
        errors = check_pr.validate_body(text)
        self.assertTrue(errors, "模板原样提交不应通过，占位必须被识别出来")

    @unittest.skipUnless(os.path.exists(_TEMPLATE_PATH), "模板文件不存在")
    def test_template_contains_required_markers(self):
        with open(_TEMPLATE_PATH, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("<!--", text)
        self.assertIn("标题", text)
        normalized = re.sub(r"\s*\|\s*", "|", text)
        self.assertIn("新增内容|WHAT'S NEW", normalized)
        self.assertIn("漏洞修复|Bug Fixes", normalized)
        self.assertIn("优化工作|Enhancements & Patches", normalized)
        self.assertIn("下一步计划|Coming Up", normalized)
        self.assertNotIn("## 验证", text)

    def test_checker_does_not_eval_or_shell_out(self):
        with open(os.path.join(_CI_DIR, "check_pr.py"), encoding="utf-8") as handle:
            source = handle.read()
        for token in (
            "eval(",
            "exec(",
            "subprocess",
            "os.system(",
            "shell=True",
            "pickle",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
