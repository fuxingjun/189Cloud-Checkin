"""天翼云盘签到：配置文件 + 企业微信群机器人通知的本地入口。

仅负责"读配置 / 跑签到 / 发通知"，登录与签到逻辑复用 index.py，不改动原文件。

用法：
    python3 local_checkin.py
    python3 local_checkin.py -c /path/to/config.json

退出码：所有账号签到成功或今日已签到为 0；配置错误或存在失败账号为 1，
通知发送失败不影响退出码。
"""

import argparse
import json
import math
import os
import random
import sys
import time

import requests

import index

DEFAULT_CONFIG = "config.json"

# 企业微信 markdown 消息体上限为 4096 字节，预留余量后按 4000 控制。
WECOM_MAX_BYTES = 4000

STATUS_ICON = {"signed": "🎉", "already_signed": "✅", "failed": "❌"}


def default_config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), DEFAULT_CONFIG)


def load_config(path):
    """读取并校验配置文件；任何问题都在发起网络请求前抛出 ValueError。"""
    if not os.path.isfile(path):
        raise ValueError("找不到配置文件：{}（可复制 config.example.json 为 config.json）".format(path))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except OSError as exc:
        raise ValueError("配置文件无法读取：{}".format(type(exc).__name__)) from None
    except ValueError:
        # UnicodeDecodeError 也是 ValueError 子类，坏编码的文件同样走这里。
        raise ValueError("配置文件不是合法 JSON：{}".format(path)) from None
    if not isinstance(raw, dict):
        raise ValueError("配置文件顶层必须是 JSON 对象")

    configured = raw.get("accounts")
    if not isinstance(configured, list) or not configured:
        raise ValueError("accounts 必须是非空数组")
    accounts = []
    for number, account in enumerate(configured, 1):
        if not isinstance(account, dict) or any(
            not isinstance(account.get(key), str) or not account[key].strip()
            for key in ("username", "password")
        ):
            raise ValueError("第 {} 个账号必须包含非空字符串 username 和 password".format(number))
        accounts.append({"username": account["username"], "password": account["password"]})

    # 可选字段：缺省或显式 null 都视为默认值；类型错误必须报错，不能被静默吞掉。
    webhook = raw.get("wecom_webhook")
    if webhook is None:
        webhook = ""
    if not isinstance(webhook, str):
        raise ValueError("wecom_webhook 必须是字符串")
    webhook = webhook.strip()

    mentions = raw.get("wecom_mention")
    if mentions is None:
        mentions = []
    if not isinstance(mentions, list) or any(not isinstance(item, str) for item in mentions):
        raise ValueError("wecom_mention 必须是字符串数组")
    mentions = [item.strip() for item in mentions]
    if any(not item for item in mentions):
        raise ValueError("wecom_mention 不能包含空白项")

    interval = raw.get("request_interval")
    if interval is None:
        interval = [1, 3]
    # Python 的 json 会接受 1e999/Infinity/NaN，这些值会让 time.sleep 在运行中崩溃。
    if (not isinstance(interval, list) or len(interval) != 2
            or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                   for value in interval)
            or not all(math.isfinite(value) for value in interval)
            or interval[0] < 0 or interval[1] < interval[0]):
        raise ValueError("request_interval 必须是 [最小秒数, 最大秒数]，均不小于 0 且最小不大于最大")

    return {"accounts": accounts, "webhook": webhook, "mentions": mentions,
            "interval": (interval[0], interval[1])}


def run_checkin(accounts, interval):
    """依次处理账号，单个账号失败不中断其他账号。"""
    results = []
    for position, account in enumerate(accounts):
        results.append(index.process_account(account, position + 1, len(accounts)))
        if position < len(accounts) - 1 and interval[1] > 0:
            time.sleep(random.uniform(interval[0], interval[1]))
    return results


def payload_size(content):
    return len(json.dumps({"msgtype": "markdown", "markdown": {"content": content}},
                          ensure_ascii=False).encode("utf-8"))


def format_mentions(mentions):
    text = " ".join("<@{}>".format(item) for item in mentions or [])
    return ("\n" + text) if text else ""


def account_lines(result):
    """单账号报告块；动态内容放入行内代码，避免特殊字符改变 markdown 排版。"""
    icon = STATUS_ICON[result["status"]]
    name = str(result["username"]).replace("`", "'")
    detail = str(result["error"] or result["signin"]).replace("`", "'")
    return ["{} `{}`".format(icon, name),
            "> `{}`".format(detail) if detail else ">", ""]


def build_report(results, mentions=None, max_bytes=WECOM_MAX_BYTES):
    """生成 markdown 报告；账号已由 process_account 脱敏。

    超长时优先省略账号明细并保留标题与统计（注明省略数量），
    字节级兜底截断由 build_wecom_payload 负责。
    """
    counts = index.summarize(results)
    header = ["## 🌥️ 天翼云盘签到报告", ""]
    summary = [
        "**📊 统计 · 共 {} 个账号**".format(len(results)),
        "🎉 本次签到 {} · ✅ 今日已签到 {} · ❌ 失败或未知 {}".format(
            counts["signed"], counts["already_signed"], counts["failed"]),
    ]
    blocks = [account_lines(result) for result in results]
    mentions_line = format_mentions(mentions)

    def assemble(hidden):
        lines = list(header)
        for block in blocks:
            lines.extend(block)
        if hidden:
            lines.extend(["……（已省略 {} 个账号明细，完整结果见运行日志）".format(hidden), ""])
        return "\n".join(lines + summary)

    hidden = 0
    while blocks and payload_size(assemble(hidden) + mentions_line) > max_bytes:
        blocks.pop()
        hidden = len(results) - len(blocks)
    return assemble(hidden)


def build_wecom_payload(message, mentions, max_bytes=WECOM_MAX_BYTES):
    """构造 markdown 消息体；超长时按行截断，作为报告级截断之后的字节级兜底。"""
    mentions_line = format_mentions(mentions)
    if payload_size(message + mentions_line) <= max_bytes:
        return {"msgtype": "markdown", "markdown": {"content": message + mentions_line}}

    notice = "\n……（内容过长已截断，完整结果见运行日志）"
    # 极小的 max_bytes 下，优先保证 @ 提醒，提示语可舍弃。
    if payload_size(notice + mentions_line) > max_bytes:
        notice = ""
    if payload_size(notice + mentions_line) > max_bytes:
        mentions_line = ""
    kept = []
    for line in message.split("\n"):
        if payload_size("\n".join(kept + [line])) > max_bytes:
            break
        kept.append(line)
    content = "\n".join(kept)
    while content and payload_size(content + notice + mentions_line) > max_bytes:
        content = content[:-1]
    return {"msgtype": "markdown", "markdown": {"content": content + notice + mentions_line}}


def send_wecom_notification(message, webhook, mentions):
    """推送 markdown 报告；返回 (是否成功, 说明文本)。"""
    if not webhook:
        return False, "企业微信未配置"

    payload = build_wecom_payload(message, mentions)
    try:
        response = requests.post(webhook, json=payload, timeout=(10, 15))
    except Exception as exc:
        # 异常文本可能包含完整 URL（含机器人 key），只保留异常类型。
        return False, "推送异常：{}".format(type(exc).__name__)

    if response.status_code != 200:
        return False, "HTTP {}".format(response.status_code)
    try:
        result = response.json()
    except ValueError:
        return False, "响应不是 JSON"
    if not isinstance(result, dict):
        return False, "响应结构异常"
    if result.get("errcode") in (0, "0"):
        return True, "已推送"
    return False, "errcode {} {}".format(result.get("errcode"), result.get("errmsg"))


def parse_args(argv):
    parser = argparse.ArgumentParser(description="天翼云盘签到（配置文件 + 企业微信通知）")
    parser.add_argument("-c", "--config", default=default_config_path(),
                        help="配置文件路径，默认为脚本同目录下的 {}".format(DEFAULT_CONFIG))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print("配置错误：{}".format(exc))
        return {"ok": False, "config_error": str(exc), "notification": "not_attempted"}

    accounts = config["accounts"]
    print("天翼云盘个人签到，账号数量：{}".format(len(accounts)))
    print("企业微信通知：{}".format("已启用" if config["webhook"] else "未启用"))

    results = run_checkin(accounts, config["interval"])
    report = build_report(results, config["mentions"])
    print(report)

    notification = "disabled"
    if config["webhook"]:
        sent, detail = send_wecom_notification(report, config["webhook"], config["mentions"])
        notification = "sent" if sent else "failed"
        print("企业微信通知：{}".format(detail))

    counts = index.summarize(results)
    return {"ok": counts["failed"] == 0, "counts": counts,
            "notification": notification, "results": results}


if __name__ == "__main__":
    sys.exit(0 if main()["ok"] else 1)
