# Strata API 密钥管理手册（现行有效）

> 生效日期：2026-10-19 ｜ 状态：已实施并验证通过
> 本文档是 API key 使用与管理的权威参考。架构：用户 → API 网关（8082，验证 key + 记录用量）→ Strata（8081，仅本机）。

## 一、现行 key 清单

key 文件：`E:\strata\gateway-keys.json`

| 使用者 | key | 用途 |
|---|---|---|
| 用户1 | `<key-1>` | 日常使用 |
| 用户2 | `<key-2>` | 日常使用 |
| 用户3 | `<key-3>` | 日常使用 |
| 用户4 | `<key-4>` | 日常使用 |
| 用户5 | `<key-5>` | 日常使用 |
| 管理员 | `<admin-key>` | **仅您持有**：查用量页 / Strata 直连（密钥不入库，本地保管） |

- 旧统一 key（32 位）已于 10-19 作废
- 部署记录.md 中不再有明文 key，全部以本文件为准

## 二、使用者接入方法（发给局域网用户）

### 接入地址

```text
地址：http://<strata-host>:8082   （或浏览器直接打开网页聊天）
密钥：找管理员领取（每人一个）
```

### 浏览器聊天（最简单）

打开 http://<strata-host>:8082 ，页面要求鉴权时填入自己的 key。对话、图片识别均可用。

### curl

```bash
curl http://<strata-host>:8082/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 你的key" \
  -d '{"model":"strata","messages":[{"role":"user","content":"你好"}],"max_tokens":64}'
```

### Python（openai SDK）

```python
from openai import OpenAI
client = OpenAI(base_url="http://<strata-host>:8082/v1", api_key="你的key")
resp = client.chat.completions.create(
    model="strata",
    messages=[{"role": "user", "content": "你好"}],
    max_tokens=256,
)
print(resp.choices[0].message.content)
```

### Cursor / Trae 等 IDE

```text
Base URL: http://<strata-host>:8082/v1
API Key:  你的key
Model:    strata
```

### Claude Code（Anthropic 兼容）

```powershell
$env:ANTHROPIC_BASE_URL  = "http://<strata-host>:8082"
$env:ANTHROPIC_AUTH_TOKEN = "你的key"
$env:ANTHROPIC_MODEL     = "claude-sonnet-4-20250514"  # 名字随意，服务端忽略
```

## 三、管理员日常操作

### 启动 / 停止

```powershell
# 启动（两个窗口，先模型后网关）
Start-Process "E:\strata\run-iq2_xs.bat"    # 等约90秒出现 ready
Start-Process "E:\strata\run-gateway.bat"   # 网关启动即就绪

# 停止：直接关闭两个窗口
```

### 新增用户

```powershell
# 1. 生成新 key
& "E:\strata\.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_hex(16))"
```

2. 编辑 `gateway-keys.json`，加一行：`"用户6": "新生成的key"`
3. 重启网关窗口（关闭 run-gateway.bat 窗口再重开，秒级，不影响 Strata）

### 吊销用户

从 `gateway-keys.json` 删除对应行 → 重启网关窗口。该 key 立即失效（401），不影响其他人。

### 改使用者名字

直接改 `gateway-keys.json` 里引号内的名字 → 重启网关。历史用量记录里的名字不会追溯变更（数据库按当时名字记录）。

### 查看用量

| 方式 | 方法 |
|---|---|
| 浏览器（最简单） | 直接打开 http://127.0.0.1:8082/usage?key=<admin-key> |
| 命令行报表 | `& "E:\strata\.venv\Scripts\python.exe" E:\strata\tools\strata-gateway.py --report`（近30天） |
| 指定天数 | `--report --days 7` |
| 原始数据 | `E:\strata\gateway-usage.db`（SQLite，字段：时间/用户/接口/prompt_tokens/completion_tokens/耗时ms） |

### 用量清零

停止网关 → 删除 `gateway-usage.db` → 重启网关（自动重建空库）。

## 四、技术细节（排障用）

| 项目 | 值 |
|---|---|
| 网关程序 | `E:\strata\tools\strata-gateway.py`（纯标准库，零依赖） |
| 网关监听 | `0.0.0.0:8082` |
| Strata 本体 | `127.0.0.1:8081`（仅本机，api_key = 管理 key） |
| 防火墙 | 需放行入站 TCP 8082（8081 规则已删） |
| 流式响应 | 网关逐块转发 SSE，打字机效果不受影响 |

### 常见问题

| 症状 | 处理 |
|---|---|
| 用户全部 401 | 网关是否在运行；key 是否复制完整（32位hex，无空格） |
| 网关 502 backend unreachable | Strata（8081）未启动或未就绪，先看 run-iq2_xs 窗口日志 |
| /usage 页 401 | 需用管理 key，不是用户 key |
| 局域网访问不了 8082 | 防火墙规则是否加了 8082（见下）；路由器 AP 隔离 |

### 防火墙规则重建（管理员 PowerShell）

```powershell
netsh advfirewall firewall add rule name="Strata Gateway 8082" dir=in action=allow protocol=TCP localport=8082
```

## 五、安全须知

- key 与使用者一一对应，泄露可精确吊销，不波及他人
- 管理 key 仅您持有；不要把它发给任何使用者（它能查全部用量，且可直连 Strata）
- 不要把 8082 端口转发到公网
- 用量库 gateway-usage.db 含使用时间分布，属内部数据，勿外传
