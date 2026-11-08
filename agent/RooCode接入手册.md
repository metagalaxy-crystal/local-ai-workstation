# Roo Code 接入手册

> 在 VSCode + Roo Code 中接入本地 llama-server，作为交互主力轨（v5 双轨制）。
> 环境基线：RTX 5060 Laptop 8GB / Windows / llama-server `:8080` ｜ 编写日期：2026-10-23

相关文档：[agent/README.md](README.md)（v5 设计方案）、[MCP调用教程.md](../tools/storytold-ArtCraft/ai-agent/MCP调用教程.md)（Craft 家族 MCP）

---

## 一、启动本地服务

Roo Code 走 OpenAI 兼容端点，先按模型注册表 `scripts\llama_cpp\models.json` 启动。**必须加 `--alias`**，否则 Roo Code 的 Model ID 显示为 gguf 文件名，容易填错。

```powershell
# 日常主力（8B MoE，激活 1B，约 222 tok/s，工具调用最干净）
uv run python scripts/llama_cpp/start_server.py lfm --alias lfm

# 高质量档（35B MoE，显存约 4-5GB，专家层留内存）
uv run python scripts/llama_cpp/start_server.py qwen36 --alias qwen36
```

验证端点：

```powershell
curl http://127.0.0.1:8080/v1/models
```

应返回 `{"data":[{"id":"lfm",...}]}`。

---

## 二、Roo Code 基础配置

1. VSCode 扩展市场安装 **Roo Code**（扩展 ID `RooVeterinaryInc.roo-cline`）
2. Settings → Providers → API Provider 选 **OpenAI Compatible**

| 字段 | 值 | 说明 |
|---|---|---|
| Base URL | `http://127.0.0.1:8080/v1` | 注意带 `/v1` |
| API Key | `local` | llama-server 不校验，但不能留空 |
| Model ID | 与 `--alias` 一致，如 `lfm` | 填错会 404 |
| Context Window | `16384` | 必须 ≤ llama-server 的 `-c`，填大不会更好 |
| Max Output Tokens | `4096` 以内 | 小模型长输出易把思考链泄进正文 |

---

## 三、多模型 Profile

Roo Code 的 API Configuration Profiles 只切换端点与模型名，**不会切换后端进程**。8GB 单卡同时只能跑一个大模型，因此正确用法如下。

| Profile | 启动命令 | 适用场景 | 显存 |
|---|---|---|---|
| `lfm` | `start_server.py lfm --alias lfm` | 日常对话、单文件编辑 | ~2GB |
| `nanbeige` | `start_server.py nanbeige --alias nb --port 8083` | 批量改写、摘要 | ~2GB |
| `qwen36` | `start_server.py qwen36 --alias qwen36` | 架构规划、疑难 bug | ~5GB |
| `minicpmv` | `start_server.py minicpmv --alias minicpmv` | 截图 / OCR（需勾选 Supports Images） | ~1GB |

**可共存的组合**：`lfm`（:8080）与 `nanbeige`（:8083）同时启动，两个 Profile 各填一个 Base URL，即实现真正的一键切换。

**端口占用表**（不要在下列端口起模型）：

| 端口 | 用途 |
|---|---|
| 8081 / 8082 | Qwen3-Embedding / Reranker 服务 |
| 8088 | 自研 Web UI |
| 8090 | 运行看板 |
| 8188 | ComfyUI |

**配合 Modes 分工**（效果优于单模型跑全部场景）：Architect 用 `qwen36`，Code 用 `nanbeige`，Ask 用 `lfm`。

---

## 四、小模型必须调的设置

| 设置项 | 建议值 | 原因 |
|---|---|---|
| Temperature | 客户端不暴露温度时，后端固定：`--extra "--temp 0.3"` | 工具调用场景需确定性 |
| Max Requests（Advanced） | `15~20` | 防止小模型无限循环，比提示词约束更有效 |
| Native Tool Calling | 默认使用 XML 文本协议；开启则启动必须补 `--jinja` | 不加 `--jinja` 时模板不渲染 `tools` 字段 |
| Auto-approve | 仅放开读文件与搜索；写文件、命令执行保留人工确认 | 本地模型误操作成本高 |
| `.roorules` | 写 3~5 条硬约束（先读后改、命令用 PowerShell、产物放 `output\`） | 小模型对短规则遵循度显著高于长提示 |

`.roorules` 示例：

```
1. 修改文件前必须先读取原文件。
2. 命令一律用 PowerShell 语法，不要用 cmd 写法的 &&。
3. 生成的图片/音频/视频统一放 output\ 目录。
4. 不要创建 README 或说明文档，除非我明确要求。
```

---

## 五、MCP 挂载

Roo Code 面板 → MCP Servers → **Edit MCP Settings**，编辑 `mcp_settings.json`（Windows 默认位于 `%APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json`）。

```json
{
  "mcpServers": {
    "wordcraft": {
      "command": "D:\\models\\tools\\storytold-ArtCraft\\apps\\wordcraft\\wordcraft-cli.exe",
      "args": ["mcp"],
      "disabled": false
    },
    "deckcraft": {
      "command": "D:\\models\\tools\\storytold-ArtCraft\\apps\\deckcraft\\deckcraft-cli.exe",
      "args": ["mcp"],
      "disabled": false
    }
  }
}
```

Craft 家族统一为 `<app>-cli.exe mcp` 的 stdio 形态（JSON-RPC 2.0），完整清单见 [MCP调用教程.md](../tools/storytold-ArtCraft/ai-agent/MCP调用教程.md)。

**工具数量的关键取舍**（直接决定小模型能不能用）：

| 应用 | 工具数 | 建议 |
|---|---|---|
| wordcraft | 12+ | 推荐 |
| deckcraft / photocraft / designcraft / soundcraft / figcraft | 17~27 | 推荐，按需挂 1~2 个 |
| pdfcraft | 170 | 谨慎，单独会话使用 |
| lightcraft | 388 | **不挂**，会挤满上下文导致选错工具 |

起步只挂 `wordcraft` + `deckcraft` 两个。

**playwright-mcp 不必安装**：自研 loop 的 `agent\tools\browser.py` 已覆盖浏览器场景；Roo Code 侧优先用内置 fetch，确有需要再挂。`tools\mcp-servers\` 当前为空。

---

## 六、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 请求突然报错而非静默截断 | Roo Code 的 Context Window 超过 llama-server 的 `-c` | 把 Context Window 调到 ≤ `-c` 值 |
| 工具调用不触发 | 未开 `--jinja` 或模型不支持原生 tools | 启动加 `--jinja`；或改用 XML 协议（默认） |
| Model ID 填了不存在的名字 | 启动未加 `--alias` | 统一加 alias，并核对 `/v1/models` |
| 生成任务时报显存不足 | ComfyUI（约 8GB 独占）与 qwen36 同时运行 | 二者分时段使用，切换前先停对方 |
| 回复带大段思考链 | 模型思考模式未关 | lfm 本身非思考模型；qwen36 可加 `--think off` |
| 切换 Profile 后仍连旧模型 | Profile 只换端点，未换后端进程 | 先停旧服务，再起新服务 |

---

## 七、与自研 loop 的分工

| 场景 | 用哪个 |
|---|---|
| 交互式编码、调试、看 diff、MCP 工具链操作 | **Roo Code**（UI、审批流、插件生态现成） |
| 无人值守批处理、定时任务、脚本化产物 | **自研 loop**（`python -m agent.cli --scheduler` / `--webui`） |
| 知识库检索、ComfyUI 生成、TTS/ASR | 自研 loop 的工具族 |

两者共用同一个 llama-server 端点，无需改配置；同一时间只起一个服务进程，另一侧复用即连。
