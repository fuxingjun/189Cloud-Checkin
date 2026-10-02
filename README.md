# 189Cloud-Checkin

天翼云盘多账号个人签到工具，支持本地运行和华为云 FunctionGraph，可通过 Telegram 发送带图标的签到汇总。

新版使用 PC 登录流程，运行入口为 `index.py`。公开源码不包含账号密码，支持**环境变量优先、硬编码备用**，以 **Python 3.6** 为兼容目标。

> 另有本地入口 `local_checkin.py`：使用 `config.json` 配置文件，并把通知改为**企业微信群机器人**，不改动 `index.py`。两者互不影响，详见下文「扩展入口」一节。

## 功能

- **个人签到**：区分本次签到成功、今天已经签到、失败或结果未知。
- **多账号**：依次执行，一个账号登录或签到失败不会中断其他账号。
- **Telegram 通知**：可选开启，支持状态图标、加粗标题和账号脱敏。
- **独立结果**：通知发送失败不会把已成功的签到改判为失败。

当前版本**不执行抽奖或家庭签到**。旧抽奖流程未接通，不代表服务端已取消这些活动；旧脚本可从 Git 历史查看。

## 快速开始：本地运行

在项目目录中，使用 [uv](https://docs.astral.sh/uv/) 创建虚拟环境并安装依赖。**本地（Python 3.8+，含 3.12）请使用 `requirements-local.txt`**：

```bash
uv venv                                    # 创建 .venv，可用 --python 3.12 指定解释器
uv pip install -r requirements-local.txt
```

`requirements.txt` 中钉定的旧版本（`requests==2.24.0` 等）仅供华为云函数的 Python 3.6 运行时使用，在 Python 3.12 上导入即报错。

配置账号并运行。以下均为占位示例：

```bash
export TY_ACCOUNTS='[{"username":"YOUR_ACCOUNT","password":"YOUR_PASSWORD"}]'
uv run python index.py        # uv run 自动使用项目内 .venv，无需激活
```

没有 uv 时也可以用 pip：`python3 -m pip install -r requirements-local.txt` 后激活 venv 运行。

**运行会真实登录并签到；配置了 Telegram 后，还会发送汇总通知。** 程序执行一轮后退出，不内置定时调度。

**登录前提**：账号若开启了设备锁，自动密码登录会失败，典型报错为 `密码登录被拒绝（-133）：设备ID不存在，需要二次设备校验`。请先在 [e.dlife.cn](https://e.dlife.cn)（天翼账号）登录并关闭设备锁，再使用本工具；此前提对 `index.py` 与 `local_checkin.py` 两个入口同时生效。

多账号的环境变量内容如下：

```json
[
  {"username": "YOUR_ACCOUNT_1", "password": "YOUR_PASSWORD_1"},
  {"username": "YOUR_ACCOUNT_2", "password": "YOUR_PASSWORD_2"}
]
```

## 配置说明

### 环境变量

| 变量 | 用途 | 是否必需 |
| --- | --- | --- |
| `TY_ACCOUNTS` | 账号 JSON 数组，每项包含 `username` 和 `password` | 与硬编码账号二选一 |
| `TG_BOT_TOKEN` | Telegram Bot Token | 可选，与 `TG_CHAT_ID` 配套 |
| `TG_CHAT_ID` | Telegram 接收目标的 Chat ID | 可选，与 `TG_BOT_TOKEN` 配套 |

程序直接读取进程或云函数环境变量，**不会自动加载 `.env` 文件**。

`TY_ACCOUNTS` 必须是合法 JSON，键名和字符串使用双引号。密码中的双引号、反斜杠等字符需要按 JSON 规则转义；在终端设置时，还要注意 shell 的引号规则。程序不会自动删除密码的首尾空格。

### 硬编码配置

不使用环境变量时，可以在私有部署副本的 `index.py` 顶部填写：

```python
accounts = [
    {"username": "YOUR_ACCOUNT", "password": "YOUR_PASSWORD"}
]

TG_BOT_TOKEN = ""
TG_CHAT_ID = ""
```

只需要签到时，Telegram 两项保持为空即可。

### 配置优先级

**账号配置：**

- `TY_ACCOUNTS` 不存在：使用源码中的 `accounts`。
- `TY_ACCOUNTS` 存在：完整替代源码账号，不与其合并。
- 环境变量为空、JSON 错误、账号列表为空或字段不合法：在发起网络请求前报错，**不会回退到硬编码账号**。

**Telegram 配置：**

- 两个环境变量都不存在：使用源码中的 Telegram 配置。
- 任一环境变量存在：整体使用环境变量这一组，不与源码中的 Token 或 Chat ID 混用。
- 最终两项都为空：关闭通知。
- 仅一项非空：提示配置不完整，跳过通知，继续签到。

公开提交和发布包应保持账号及 Telegram 配置为空。私有副本与日志可放在被 Git 忽略的 `local/` 中；该目录不是公开发行内容。

## Telegram 效果

报告按账号分段，显示本次任务的真实状态。示例：

> 🌥️ **天翼云盘签到报告**
>
> 🎉 **账号 A**
>
> 签到成功，获得 50M 空间
>
> ✅ **账号 B**
>
> 今日已签到，本次未重复领取
>
> ❌ **账号 C**
>
> 登录失败：需要验证码或验证码检查异常；停止自动密码登录
>
> 📊 **统计 · 共 3 个账号**
>
> 🎉 本次签到 1 · ✅ 今日已签到 1 · ❌ 失败或未知 1

实际账号会脱敏。通知使用 Telegram HTML 格式，动态账号和错误信息会转义，避免特殊字符破坏排版。

## 华为云 FunctionGraph 部署

### 1. 准备代码和依赖

函数代码的根目录需要包含：

```text
index.py
requests/
rsa/
……其他传递依赖
```

依赖也可以通过云函数已有的兼容依赖包提供。**仅替换 `index.py` 不会自动安装依赖**。

如果使用已有 Python 3.6 函数，优先保留原运行时和依赖，替换程序后再验证。新打包时，应使用与云端运行时兼容的环境准备依赖，不要直接打包本机较新 Python 的整个安装目录。

### 2. 设置入口和配置

| 配置项 | 设置 |
| --- | --- |
| 代码文件名 | `index.py`，位于部署包根目录 |
| 函数执行入口 | `index.main_handler` |
| Python 运行时 | 以 Python 3.6 为兼容目标，实际兼容情况见下节 |
| 账号配置 | 推荐添加环境变量 `TY_ACCOUNTS`；也支持私有源码中的 `accounts` |
| Telegram | 按需设置 `TG_BOT_TOKEN`、`TG_CHAT_ID` |

处理函数不使用 `event` 中的业务参数，测试事件可以为 `{}`。**测试调用也会真实签到，并在配置完整时发送通知**。

部署包只应包含程序与依赖，不应包含测试目录、个人日志、`.env` 或 `local/` 下的私有材料。公开根目录的 `index.py` 没有预设账号，未配置就调用会得到配置错误。

### 3. 验证后配置定时触发

先用单账号核对登录、签到结果和通知，再启用多账号与定时触发。签到接口超时并不证明服务端没有执行，不要无条件重跑整个批次。

程序没有跨实例锁或持久化登录态，配置触发器时应避免重叠调用。账号较多时，需要根据实际耗时调整函数总超时，而不是只参考单个 HTTP 请求的超时。

### Python 3.6 与依赖边界

`requirements.txt` 保持以下版本：

```text
requests==2.24.0
rsa==4.7
```

- 这两个版本的包元数据允许 Python 3.6，安装时还需要它们的传递依赖。
- 程序使用 Python 3.6 可用的语法和标准库，没有引入新的第三方依赖。
- 已完成 Python 3.6 语法检查，以及较新 Python 环境中的登录、容量查询和单账号签到验证；**这不等于真实 Python 3.6 云函数环境已经验收通过**。
- Python 3.6 已结束上游维护。本项目兼容旧运行时，不代表建议新项目继续选用它；更换运行时或依赖版本后需重新验证。
- `requirements-189Checkin.zip` 是保留的历史依赖包，不含新版程序，也不是已重新验证的完整部署包。

## 如何判断执行成功

云函数返回 `statusCode: 200` 表示处理函数正常返回，**不代表所有账号签到成功，也不代表 Telegram 发送成功**。JSON 字符串 `body` 中包含：

| 字段 | 含义 |
| --- | --- |
| `ok` | 所有账号均签到成功或今日已签到时为 `true`；不包含通知是否成功 |
| `counts.signed` | 本次签到成功的账号数 |
| `counts.already_signed` | 今日已经签到的账号数 |
| `counts.failed` | 失败或结果未知的账号数 |
| `results` | 逐账号脱敏结果，包含 `status`、`signin`、`error` |
| `notification` | `disabled`、`incomplete`、`sent` 或 `failed` |

配置不合法时，`body` 返回 `ok: false`、`config_error` 和 `notification: "not_attempted"`，不会发起签到请求。

本地运行 `index.py` 时正常退出（退出码 0）同样不保证全部账号成功，应查看输出的逐账号结果和汇总；`local_checkin.py` 的退出码可直接判断成败（`0` 全部成功或已签，`1` 配置错误或存在失败账号），见上文「扩展入口」一节。

## 扩展入口：`local_checkin.py`（配置文件 + 企业微信）

原 `index.py` 保持不变。`local_checkin.py` 是独立入口，登录与签到逻辑直接复用 `index.py`，差异只有两点：**账号来源改为配置文件**、**通知改为企业微信群机器人**。不再读取任何环境变量。登录前提同上文：设备锁需先在 [e.dlife.cn](https://e.dlife.cn)（天翼账号）关闭，否则密码登录会被要求设备校验。

### 1. 准备配置

复制模板并填写自己的账号：

```bash
cp config.example.json config.json
```

```json
{
  "accounts": [
    {"username": "YOUR_ACCOUNT_1", "password": "YOUR_PASSWORD_1"},
    {"username": "YOUR_ACCOUNT_2", "password": "YOUR_PASSWORD_2"}
  ],
  "wecom_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY",
  "wecom_mention": [],
  "request_interval": [1, 3]
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `accounts` | 是 | 非空数组，每项须含非空字符串 `username`、`password`；密码首尾空格不会被自动删除 |
| `wecom_webhook` | 否 | 企业微信群机器人 Webhook 完整地址；留空则关闭通知，仅本地打印报告 |
| `wecom_mention` | 否 | 需要 @ 的人，群机器人仅支持 `all`（`["all"]`）与手机号 |
| `request_interval` | 否 | 账号之间的随机等待秒数区间，默认 `[1, 3]`；填 `[0, 0]` 表示不等待 |

`config.json` 已在 `.gitignore` 中，不会提交到版本库；仓库只公开 `config.example.json`。配置为空的模板文件也会导致程序在处理前报错退出，请在私有副本中填写。

三个可选字段省略或显式填 `null` 时使用默认值；类型不合法（如 `wecom_webhook` 填数字）会在发起网络请求前直接报错。

### 2. 获取企业微信 Webhook

在企业微信群聊中依次点击「群设置 → 群机器人 → 添加机器人」，复制生成的 Webhook 地址填入 `wecom_webhook`。该地址等同于密码，不要公开或提交。

### 3. 运行

本地依赖安装（Python 3.8+，含 3.12，推荐 [uv](https://docs.astral.sh/uv/)）：

```bash
uv venv
uv pip install -r requirements-local.txt
```

**注意**：不要在本地 venv 中安装 `requirements.txt`——其中钉定的 `requests==2.24.0` 依赖 `urllib3 1.25.x`，在 Python 3.12 上导入即报 `No module named 'urllib3.packages.six.moves'`。那份钉定版本仅供华为云函数的 Python 3.6 运行时使用。

```bash
uv run python local_checkin.py
uv run python local_checkin.py -c /path/to/config.json   # 指定配置文件位置
# 或激活后运行：source .venv/bin/activate && python local_checkin.py
```

默认读取**脚本同目录**下的 `config.json`，因此从任意工作目录执行都可以；`-c` 可指定其他路径。

退出码：所有账号签到成功或今日已签到为 `0`；配置错误或存在失败账号为 `1`，便于 shell 脚本与定时任务判断。通知发送失败不影响退出码。

输出示例（同时写入企业微信群）：

```text
天翼云盘个人签到，账号数量：2
企业微信通知：已启用
账号 [1/2]：acc***rd
🎉 `acc***rd`
> `签到成功，获得 50M 空间`
...
企业微信通知：已推送
```

### 与 `index.py` 的行为差异

| 项目 | `index.py` | `local_checkin.py` |
| --- | --- | --- |
| 配置来源 | 环境变量优先，硬编码备用 | 仅 `config.json` |
| 通知渠道 | Telegram（HTML） | 企业微信群机器人（markdown） |
| 账号之间间隔 | 固定随机 1–3 秒 | 由 `request_interval` 控制 |
| 配置错误 | 返回 `config_error`，不发起请求 | 打印错误并退出，不发起请求 |

其他约束一致：每个账号独立处理、单账号失败不中断其他账号；通知推送失败不会把已成功的签到改判为失败；不保存 Cookie 或登录态，每次运行重新登录。

账号名与结果详情以行内代码渲染，避免账号脱敏用的 `***` 或错误信息中的特殊字符改变 markdown 排版。账号较多导致报告超出企业微信消息上限（4096 字节）时，会自动省略部分账号明细并保留统计（通知中注明省略数量），完整结果以运行日志为准。

## 常见问题

| 现象 | 应检查什么 |
| --- | --- |
| 提示未配置账号或 JSON 错误 | 检查 `TY_ACCOUNTS`，确认不是空字符串、空数组或无效 JSON；即使硬编码有账号，错误的环境变量也不会被忽略 |
| 硬编码账号没有生效 | 检查运行环境是否仍设置了 `TY_ACCOUNTS` |
| `No module named requests` 或 `rsa` | 函数缺少依赖，或依赖包的目录层级不正确 |
| 缺少 PC 登录页字段 | 返回页面不符合当前解析规则，需结合阶段日志检查；不应直接认定密码错误 |
| 密码登录被拒绝（-133）：设备ID不存在，需要二次设备校验 | 账号开启了设备锁：先在 [e.dlife.cn](https://e.dlife.cn)（天翼账号）关闭设备锁再重试 |
| 需要验证码或设备校验 | 先确认已在 [e.dlife.cn](https://e.dlife.cn)（天翼账号）关闭设备锁再重试；当前不处理验证码、短信或扫码交互；不要反复尝试相同密码请求 |
| 签到成功但通知没收到 | 单独检查 `notification`、Telegram 配置、机器人会话权限及函数到 Telegram 的网络访问 |
| 仍出现旧版“没有找到 href 链接” | 检查实际运行文件、函数入口与部署版本，确认已使用新版 `index.py` |
| 只有个人签到，没有抽奖 | 这是当前版本的功能范围，不是抽奖已经执行失败 |

默认关闭 `PRINT_RESPONSE_BODY`。需要辅助排查时可开启，它只输出白名单业务状态或 HTTP 状态，不输出完整认证响应。

旧版本使用的 `username`、`password`、`TGBOTAPI`、`TGID` 环境变量不由新版自动读取，应迁移为本页列出的配置名称。旧脚本和旧 GitHub Actions 调度文件已移除；本仓库当前不提供开箱即用的 Actions 定时签到工作流。

## 开发与测试

```bash
uv run python -m unittest discover -s tests -v
```

测试模拟网络请求，不登录真实账号、不签到、不发送 Telegram 或企业微信消息。覆盖配置优先级、配置文件校验、账号隔离、签到状态、通知排版、企微消息体长度控制和动态内容转义等行为。

只在明确需要时进行真实账号验证，并分别确认登录、签到和通知结果。每次运行重新登录，不保存 Cookie、Session 或 Token；长期运行可能需要人工处理服务端风控。

## License

[Apache License 2.0](LICENSE)
