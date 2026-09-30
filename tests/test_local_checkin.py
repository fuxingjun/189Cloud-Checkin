import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

import index as app
import local_checkin as local


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.path = os.path.join(self.directory, "config.json")

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as handle:
            if isinstance(data, str):
                handle.write(data)
            else:
                json.dump(data, handle, ensure_ascii=False)

    def valid(self, **overrides):
        data = {"accounts": [{"username": "u", "password": "p"}]}
        data.update(overrides)
        return data

    def test_missing_file_is_reported_before_network(self):
        with self.assertRaises(ValueError) as ctx:
            local.load_config(os.path.join(self.directory, "absent.json"))
        self.assertIn("找不到配置文件", str(ctx.exception))

    def test_invalid_json_and_shape(self):
        for raw in ("", "not-json", "[]", '"text"', "null"):
            with self.subTest(raw=raw):
                self.write(raw)
                with self.assertRaises(ValueError):
                    local.load_config(self.path)

    def test_account_validation(self):
        raised = [
            {"accounts": []},
            {"accounts": {}},
            {"accounts": [{}]},
            {"accounts": [{"username": "a"}]},
            {"accounts": [{"username": "a", "password": "  "}]},
            {"accounts": [{"username": 1, "password": "p"}]},
        ]
        for data in raised:
            with self.subTest(data=data):
                self.write(data)
                with self.assertRaises(ValueError):
                    local.load_config(self.path)

    def test_password_is_not_trimmed(self):
        self.write(self.valid(accounts=[{"username": "u", "password": " p "}]))
        self.assertEqual(local.load_config(self.path)["accounts"][0]["password"], " p ")

    def test_optional_field_validation(self):
        # 0/false 等错误类型不得被当作"未配置"静默跳过。
        for data in ({"request_interval": [3, 1]}, {"request_interval": [1]},
                     {"request_interval": "1,3"}, {"request_interval": [True, 3]},
                     {"request_interval": [-1, 3]},
                     {"wecom_mention": "all"}, {"wecom_mention": [1]},
                     {"wecom_mention": ["  "]},
                     {"wecom_webhook": 12}, {"wecom_webhook": 0}):
            with self.subTest(data=data):
                self.write(self.valid(**data))
                with self.assertRaises(ValueError):
                    local.load_config(self.path)

    def test_interval_rejects_non_finite_numbers(self):
        # json 会把 1e999 解析为 inf，若放行会在 time.sleep 中崩溃。
        self.write('{"accounts":[{"username":"u","password":"p"}],'
                   '"request_interval":[0,1e999]}')
        with self.assertRaises(ValueError):
            local.load_config(self.path)

    def test_defaults_when_optional_keys_absent(self):
        self.write(self.valid())
        config = local.load_config(self.path)
        self.assertEqual((config["webhook"], config["mentions"], config["interval"]),
                         ("", [], (1, 3)))

    def test_null_optional_keys_use_defaults(self):
        self.write('{"accounts":[{"username":"u","password":"p"}],"wecom_webhook":null,'
                   '"wecom_mention":null,"request_interval":null}')
        config = local.load_config(self.path)
        self.assertEqual((config["webhook"], config["mentions"], config["interval"]),
                         ("", [], (1, 3)))

    def test_mentions_are_trimmed(self):
        self.write(self.valid(wecom_mention=[" all ", "13800000000 "]))
        self.assertEqual(local.load_config(self.path)["mentions"], ["all", "13800000000"])

    def test_args_default_config(self):
        self.assertEqual(local.parse_args([]).config, local.default_config_path())
        self.assertEqual(local.parse_args(["-c", "x.json"]).config, "x.json")

    def test_config_error_stops_before_login(self):
        self.write("bad-json")
        with patch.object(app, "login") as login:
            result = local.main(["-c", self.path])
        self.assertFalse(result["ok"])
        self.assertEqual(result["notification"], "not_attempted")
        login.assert_not_called()


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    @staticmethod
    def ok_response():
        response = Mock(status_code=200)
        response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        return response

    def test_sends_markdown_with_mentions(self):
        with patch.object(local.requests, "post", return_value=self.ok_response()) as post:
            sent, detail = local.send_wecom_notification("报告", "https://example.invalid/hook", ["all"])
        self.assertTrue(sent)
        self.assertEqual(detail, "已推送")
        payload = post.call_args[1]["json"]
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertIn("<@all>", payload["markdown"]["content"])
        self.assertEqual(post.call_args[0][0], "https://example.invalid/hook")

    def test_no_webhook_is_disabled(self):
        with patch.object(local.requests, "post") as post:
            sent, detail = local.send_wecom_notification("报告", "", [])
        self.assertFalse(sent)
        self.assertEqual(detail, "企业微信未配置")
        post.assert_not_called()

    def test_business_error_and_exception_are_reported(self):
        response = Mock(status_code=200)
        response.json.return_value = {"errcode": 93000, "errmsg": "invalid webhook url"}
        with patch.object(local.requests, "post", return_value=response):
            sent, detail = local.send_wecom_notification("报告", "https://example.invalid/x", [])
        self.assertFalse(sent)
        self.assertIn("93000", detail)

        with patch.object(local.requests, "post", side_effect=requests.Timeout("secret")):
            sent, detail = local.send_wecom_notification("报告", "https://example.invalid/x", [])
        self.assertFalse(sent)
        self.assertEqual(detail, "推送异常：Timeout")

    def test_http_error_non_json_and_non_dict_responses(self):
        response = Mock(status_code=500)
        with patch.object(local.requests, "post", return_value=response):
            self.assertEqual(local.send_wecom_notification("a", "https://x.invalid", [])[1], "HTTP 500")

        response = Mock(status_code=200)
        response.json.side_effect = ValueError("not json")
        with patch.object(local.requests, "post", return_value=response):
            self.assertEqual(local.send_wecom_notification("a", "https://x.invalid", [])[1], "响应不是 JSON")

        # 服务端返回 JSON 数组等非对象结构时不能抛 AttributeError。
        response = Mock(status_code=200)
        response.json.return_value = ["unexpected"]
        with patch.object(local.requests, "post", return_value=response):
            self.assertEqual(local.send_wecom_notification("a", "https://x.invalid", [])[1], "响应结构异常")

    def test_long_message_is_truncated_within_limit(self):
        message = "## 报告\n" + "\n".join("🎉 **account-{}** 签到成功".format(i) for i in range(400))
        for mentions in ([], ["all"]):
            with self.subTest(mentions=mentions):
                payload = local.build_wecom_payload(message, mentions, max_bytes=600)
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.assertLessEqual(len(body), 600)
                self.assertIn("已截断", payload["markdown"]["content"])
                if mentions:
                    self.assertIn("<@all>", payload["markdown"]["content"])

    def test_tiny_limit_degrades_gracefully(self):
        # 连提示语都放不下时按优先级舍弃；预算小于 JSON 信封（约 52 字节）时只能返回空内容。
        payload = local.build_wecom_payload("很长的文本" * 100, ["all"], max_bytes=50)
        self.assertEqual(payload["markdown"]["content"], "")

        payload = local.build_wecom_payload("很长的文本" * 100, ["all"], max_bytes=120)
        self.assertIn("<@all>", payload["markdown"]["content"])
        self.assertLessEqual(local.payload_size(payload["markdown"]["content"]), 120)

    def test_notification_failure_keeps_sign_result(self):
        results = [{"username": "masked", "status": "signed", "signin": "成功", "error": None}]
        with patch.object(local, "load_config", return_value={"accounts": [{}], "webhook": "https://x.invalid",
                                                              "mentions": [], "interval": (0, 0)}), \
                patch.object(local, "run_checkin", return_value=results), \
                patch.object(local, "send_wecom_notification", return_value=(False, "errcode 93000")):
            result = local.main([])
        self.assertTrue(result["ok"])
        self.assertEqual(result["notification"], "failed")

    def test_notification_disabled_without_webhook(self):
        results = [{"username": "masked", "status": "signed", "signin": "成功", "error": None}]
        with patch.object(local, "load_config", return_value={"accounts": [{}], "webhook": "",
                                                              "mentions": [], "interval": (0, 0)}), \
                patch.object(local, "run_checkin", return_value=results), \
                patch.object(local, "send_wecom_notification") as sender:
            result = local.main([])
        self.assertEqual(result["notification"], "disabled")
        sender.assert_not_called()

    def test_interval_zero_skips_sleep(self):
        accounts = [{"username": "a", "password": "b"}, {"username": "c", "password": "d"}]
        with patch.object(app, "process_account", return_value={"username": "x", "status": "signed",
                                                                "signin": "", "error": None}) as process, \
                patch.object(local.time, "sleep") as sleep:
            local.run_checkin(accounts, (0, 0))
        self.assertEqual(process.call_count, 2)
        sleep.assert_not_called()


class ReportTests(unittest.TestCase):
    @staticmethod
    def result(name, status, signin="", error=None):
        return {"username": name, "status": status, "signin": signin, "error": error}

    def test_report_uses_code_spans_and_keeps_counts(self):
        report = local.build_report([
            self.result("acc-a", "signed", "获得 <63>M"),
            self.result("acc-b", "already_signed", "已签到"),
            self.result("acc-c", "failed", error='失败 <x> & "q"'),
        ])
        self.assertIn("## 🌥️ 天翼云盘签到报告", report)
        self.assertIn("🎉 `acc-a`", report)
        self.assertIn("> `获得 <63>M`", report)
        self.assertIn('`失败 <x> & "q"`', report)
        self.assertIn("共 3 个账号", report)
        for text in ("本次签到 1", "今日已签到 1", "失败或未知 1"):
            self.assertIn(text, report)

    def test_report_neutralizes_backticks_and_empty_detail(self):
        report = local.build_report([
            self.result("a`b", "failed", error="x`y"),
            self.result("acc-d", "failed"),
        ])
        self.assertIn("`a'b`", report)
        self.assertIn("`x'y`", report)
        self.assertNotIn("a`b", report)
        self.assertNotIn("x`y", report)
        self.assertIn("\n>\n", report)  # 空详情渲染为空引用行

    def test_report_truncation_keeps_summary(self):
        results = [self.result("acc-{:03d}".format(i), "signed", "签到成功，获得 63M 空间")
                   for i in range(100)]
        report = local.build_report(results, max_bytes=1000)
        self.assertIn("共 100 个账号", report)
        self.assertIn("已省略", report)
        self.assertLessEqual(local.payload_size(report), 1000)
        shown = report.count("🎉 `acc-")
        self.assertGreater(shown, 0)
        self.assertLess(shown, 100)

    def test_report_accounts_for_mentions_in_size(self):
        results = [self.result("acc-{}".format(i), "signed", "ok") for i in range(60)]
        mentions = ["1380000000{}".format(i) for i in range(9)]
        report = local.build_report(results, mentions, max_bytes=1000)
        payload = local.build_wecom_payload(report, mentions)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.assertLessEqual(len(body), local.WECOM_MAX_BYTES)
        self.assertIn("<@13800000000>", payload["markdown"]["content"])


class IsolationTests(unittest.TestCase):
    """确认新入口没有改动原 index.py 的行为。"""

    def test_index_still_uses_environment_config(self):
        output = contextlib.redirect_stdout(io.StringIO())
        with output, patch.dict(app.os.environ, {"TY_ACCOUNTS": json.dumps(
                [{"username": "u", "password": "p"}])}, clear=True), \
                patch.object(app, "process_account", return_value={"username": "x", "status": "signed",
                                                                   "signin": "", "error": None}):
            self.assertTrue(app.main()["ok"])
        self.assertIsNone(app.load_config.__defaults__[0])


if __name__ == "__main__":
    unittest.main()
