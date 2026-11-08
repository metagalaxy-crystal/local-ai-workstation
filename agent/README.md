# 本地 Agent 设计方案 v5

> 目标：在现有 `D:\models` 推理环境之上，搭建一个功能完整的本地 Agent——能多轮调用工具、浏览网页、检索记忆、操作文件、执行代码，并能调用已有的多模态生成能力（图/视频/音乐/TTS）。
> 创建日期：2026-10-22 ｜ 硬件基线：RTX 5060 Laptop 8GB / 32GB RAM ｜ D 盘实测剩余 66.6 GB

---

## 1. 目标与边界

**做**：
- 单机本地运行，全部推理走本地模型（llama-server + ComfyUI + 既有 Python 推理栈）
- 工具调用循环（tool-call loop）、任务分解、失败重试
- 浏览器控制、网络搜索、文件/Shell/代码沙箱
- 跨会话记忆 + 本地文档知识库（RAG）
- 挂载 ComfyUI 生成工具，让 Agent 具备图/视频/音乐产出能力

**不做（本期）**：
- 多 Agent 分布式协作
- 云端 API 混合路由（保留接口，不实现）
- 手机/远程控制

## 2. 总体架构

![本地 Agent 能力栈：已有 vs 待补](assets/agent-capability-stack.png)
*图 1：能力栈盘点——绿点为已具备，虚线为待补齐，"Agent 循环"为核心缺口（P0）*

```
用户 → CLI（P0）→ Web UI（P2）
        └─ Agent Loop（Python，自研）
            ├─ LLM 通道   : llama-server（OpenAI 兼容 /v1/chat/completions）
            │               主脑 Qwen3.6-35B-A3B / 轻任务 Nanbeige4.2-3B
            ├─ 工具层
            │   ├─ 内置工具: 文件、Shell、Python 沙箱、搜索、浏览器(Playwright)
            │   ├─ MCP 工具: playwright-mcp（可选）、Craft 家族（已有）
            │   └─ 生成工具: comfy_client.py 封装 → 文生图/视频/音乐
            ├─ 记忆层
            │   ├─ 会话存储: SQLite（消息 + 任务状态）
            │   └─ 向量检索: sqlite-vec + Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B
            └─ 护栏: 最大轮数、单工具超时、失败重试 1 次、历史裁剪
```

**主循环伪代码**（核心 ~300 行）：

```
while 轮次 < MAX_ROUNDS:
    resp = chat(messages, tools=all_tools)
    if resp.tool_calls:
        for tc in resp.tool_calls:
            result = run_tool(tc, timeout=60, retry=1)
            messages.append(tool_result(result))
        messages = trim_history(messages)   # 保留 system + 近 N 轮 + 工具结果摘要
    else:
        save_session(); return resp.content
```

## 3. 框架选择

### 3.1 Agent 编排：自研轻量 loop ✅

| 方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **自研 loop** | 完全可控、依赖极轻、贴合 llama-server 与本地显存调度、Craft MCP 经验直接复用 | 重试/裁剪需自己写（量级小） | **采用** |
| LangGraph | 生态全、有可视化 | 抽象厚、依赖重（数百 MB）、云端 API 导向、调试黑盒 | 不采用 |
| smolagents | HF 出品、CodeAgent 轻量 | 代码即动作模式与已验证的原生 tool-calling 资产不匹配 | 不采用 |
| Letta/MemGPT | 自带记忆系统 | 自建服务重、绑定自有存储、定制困难 | 不采用 |
| browser-use | 半天即可跑通浏览器 demo | 自带 loop 会与自研骨架冲突 | 仅作 P1 浏览器验证 |

**选型依据**：本项目特殊点多（llama.cpp 端点、MoE CPU 卸载、ComfyUI 显存互斥、MCP 混用），框架抽象反而碍事；Qwen3.6-35B 工具调用已实测满分，loop 只是薄薄一层包装。
**（v5 修订）**：loop 仍自研但定位收缩为"自动化任务引擎"；日常交互改走现成平台（见 3.5 双轨制）。成熟框架的提示模板多为云端大模型调校，直接套在 30B 级本地模型上反而放大 tool-call 格式退化风险——薄 loop + 原生 tool calling 才是小模型最稳的形态，这也是 Cline 官方为本地模型提供 Compact Prompt（压缩约 90% 提示）的原因。

### 3.2 浏览器：Playwright（Python 原生）为主，playwright-mcp 为增强

- **P1 先用 Python playwright 原生工具**：`navigate / click / fill / extract / screenshot` 5~6 个原子工具，走 DOM 可访问性树，零截图识别模型、零额外显存，8GB 显存下唯一可行路线
- **P2 可选升级 playwright-mcp**（本机 Node v24.14.1 已满足）：标准化 MCP 接口，与 Craft 工具同一套接入协议
- **不用 browser-use 做常驻**：验证用完即弃
- 模型分工：Qwen3.6-35B 读 DOM 做决策；Qwen2.5-VL-7B 只在需要"看页面截图"时按需加载

### 3.3 检索/记忆：Qwen3-Embedding-0.6B + sqlite-vec + Qwen3-Reranker-0.6B

| 组件 | 选择 | 理由 |
|---|---|---|
| Embedding | Qwen3-Embedding-0.6B GGUF（Q8_0） | llama.cpp 原生 `--embedding` 支持，OpenAI 兼容 `/v1/embeddings`，中文效果好 |
| 向量库 | **sqlite-vec**（pip 包） | 零服务、零 Docker、单文件，贴合本项目扁平目录风格；Chroma/FAISS 均需额外服务或依赖 |
| Reranker | Qwen3-Reranker-0.6B GGUF | llama.cpp 已支持 rerank 端点；召回 top-20 → 精排 top-5 |
| 会话存储 | SQLite 单文件 | 零依赖；与向量库同目录 |

### 3.4 接口层：CLI 先行，Web UI 后置

- P0：`python -m agent.cli` 交互命令行（复用 .venv）
- P2a（已落地）：运行看板用**标准库 `http.server`** 单文件服务（:8090），不引入 FastAPI——只需轮询 `/state` 与预览图，FastAPI 的体量与启动成本在此不划算
- P2：FastAPI + 单页前端（不引入 Open WebUI，其依赖体积与定制性均不合适）
- **（v5 修订）**：交互式 Web UI 降级为可选——"类 VSCode UI"需求由 3.5 的 Roo Code 路线直接满足，自建 Web UI 仅在双轨制验证后仍不满足时再做

### 3.5 平台层选型（v5 新增：UI / 插件生态 / 模型切换 / 监控）

**需求合理性评估**：

| 需求 | 评估 | 结论 |
|---|---|---|
| 用成熟框架替代自研 | 框架解决不了小模型适配，反而引入大模型调校的提示模板 | loop 保持自研（收缩为自动化引擎）；交互层换现成平台 |
| 类 VSCode UI + 庞大插件库 | 合理；2026 年"插件库"的事实标准是 MCP 生态 | 直接用 VSCode + Roo Code——UI 即 VSCode 本体，插件即 MCP Marketplace + 编辑器插件生态 |
| 运行中切换模型 | 合理，成本低 | Roo Code API Profiles 多端点一键切换；LiteLLM 网关可加自动路由/回落 |
| 全流程监控 | 合理且轻量可达成 | LiteLLM（token/调用记账）+ llama-server `--metrics` + ComfyUI `/system_stats` |

**双轨制架构**（v5 起）：

```
交互主力轨（日常对话/编码/浏览任务，P3 引入）
  VSCode + Roo Code（Cline fork，v3.21+；或 Cline v4.x）
    ├─ OpenAI Compatible provider → http://127.0.0.1:8080/v1（llama-server 直连）
    ├─ API Configuration Profiles：qwen36 / qwen25vl / lfm / nanbeige 一键切换
    ├─ MCP Marketplace：Craft、playwright-mcp、自定义工具一键接入
    └─ per-task token 统计 + 步数审批制（对本地小模型友好，防失控循环）
自动化引擎轨（无人值守/脚本化任务）
  自研 loop（本方案 §4 结构）→ 维护成本上升时可平移 PydanticAI v2
监控层（两轨共用，P3 引入）
  LiteLLM proxy：pip 安装免 Docker，本地 Postgres 记账，统一端点/路由/token 日志
  llama-server --metrics（Prometheus /metrics、/slots）+ ComfyUI /api/system_stats（VRAM/RAM）
  Grafana 聚合看板（可选）
```

**为什么不选自托管平台**（2026-10 现状调研）：

| 平台 | 现状 | 不选原因 |
|---|---|---|
| OpenHands | 官方有 Qwen3.6-35B 接入教程 | 必须 WSL2 + Docker，容器常驻数 GB，8GB 显存机器负担大 |
| Dify 1.x | 插件市场 + 监控面板齐全 | Docker Compose 全家桶 6~10GB RAM；工作流平台形态与需求错位 |
| LibreChat / LobeChat | 均可接 OpenAI 兼容端点 | 前者无原生 Windows 包；后者 agent 能力与监控弱；均需 Docker/Node 栈 |
| AnythingLLM | Windows 原生桌面免 Docker、MCP + token 统计 | RAG 问答强但 agent 编排弱——留作 P2 知识库问答备选 |
| Langfuse v3 | 追踪最全 | 自托管需 ClickHouse（官方建议 8GB RAM）+ Postgres + Redis，单人使用过重 |
| Agno | AgentOS 可暴露 MCP 服务 | 偏运行时平台，重于本需求 |

**轻量框架**：PydanticAI v2 对 llama.cpp（`openai-chat:` 前缀，注意 v2 默认 `openai:` 走 Responses API 不可直用）与 MCP（stdio/SSE）支持完善、类型安全，是自研 loop 的现成替代；P0 仍先以自研 loop 起步（零新依赖、完全可控），工具 schema 结构同源，后续迁移面小。

## 4. 目录结构

```
d:\models\agent\
├── README.md                 # 本设计方案
├── pyproject.toml            # 依赖清单（uv 管理，可独立 venv 或并入主 .venv）
├── agent\                    # 核心 Python 包（自研代码）
│   ├── cli.py                # 入口：交互式会话 / --task / --plan / --webui / --scheduler（看板默认启动，--no-monitor 关闭） ✅P0-P3
│   ├── loop.py               # 主循环（tool-call 循环、护栏、事件埋点）✅P0-P2a
│   ├── llm.py                # llama-server 客户端（chat/tools/embeddings 路由）✅P0
│   ├── context.py            # 历史裁剪与压缩 ✅P0
│   ├── planner.py            # 自主规划：在已知手段中按成本选路线 ✅P2a
│   ├── trace.py              # JSONL 事件流 + CPU/RAM/VRAM/GPU 采样 ✅P2a
│   ├── monitor.py            # 本地看板 + /metrics（步骤框图 + 仪表 + 预览 + Prometheus）✅P2a/P3
│   ├── scheduler.py          # 定时任务调度（once/interval/daily，JSON 持久化）✅P2c
│   ├── webui.py              # 轻量 Web 聊天界面（标准库 http.server，:8088）✅P2c
│   ├── tools\                # 自研工具实现（代码；第三方安装层在 d:\models\tools\）
│   │   ├── registry.py       # 工具注册（JSON schema + Python 函数统一入口）✅P0
│   │   ├── scope.py          # 路径边界 / Shell 白名单等共享状态 ✅P0
│   │   ├── proc.py           # 子进程超时杀树 + 中英混排解码 ✅P0
│   │   ├── files.py          # 读/写/列目录/移动 ✅P0
│   │   ├── shell.py          # 受限命令执行（超时+黑白名单）✅P0
│   │   ├── sandbox.py        # Python 沙箱（子进程+超时+临时目录）✅P0
│   │   ├── search.py         # 网络搜索（必应/博查/DuckDuckGo 多源）✅P1
│   │   ├── browser.py        # Playwright 原子操作（崩溃自愈 + 每步截图预览）✅P1/P2a
│   │   ├── comfy.py          # ComfyUI 生成图/视频/音乐（子进程复用 run_* 脚本）✅P2b
│   │   └── voice.py          # MOSS-TTS 合成 + Qwen3-ASR 转写/说话人分离 ✅P2b
│   ├── mcp_client.py         # MCP stdio 接入（复用 Craft 模式）✅P1
│   ├── memory\               # 记忆子系统（代码，区别于顶层 memory\ 数据目录）
│   │   ├── store.py          # SQLite 会话/消息/运行账本 ✅P0
│   │   └── rag.py            # 切片/向量化/召回/精排 ✅P1
│   └── router.py             # 模型路由（主脑/轻任务/视觉按需）✅P0
├── configs\
│   ├── agent.json            # 模型端点、轮数/超时上限、工具开关与参数（P0 暂不拆 tools.json）
│   └── litellm.yaml          # LiteLLM 网关配置（模型路由/回落/记账，P3 可选）
├── scripts\
│   ├── start_agent.bat       # 双击启动（纯 ASCII 注释）✅P0
│   └── start_embed_server.bat# 启动 embedding/rerank 服务 ✅P1
├── memory\                   # 记忆数据目录（所有 memory 存储集中于此，可重建）
│   ├── session.db            #   会话 / 任务状态（SQLite）
│   ├── vectors.db            #   向量库（sqlite-vec）
│   └── profile.md            #   长期记忆 / 用户画像快照
└── tests\                    # 工具单测 + 端到端任务集
```

> 工具层第三方组件不在 agent 目录内安装，统一放全局工具根目录 `d:\models\tools\`（与 Craft 工具链同根）：`d:\models\tools\mcp-servers\`（playwright-mcp 等含 node_modules）、`d:\models\tools\playwright-browsers\`（Chromium，PLAYWRIGHT_BROWSERS_PATH 指向此处）。
> v5 增补：LiteLLM pip 装入主 .venv（免 Docker）；如启用 spend 日志，Postgres 便携版放 `d:\models\tools\postgres\`；Roo Code/Cline 装在用户现有 VSCode 内，本仓库零占用。

## 5. 空间占用预估

D 盘当前剩余 **66.6 GB**，全案落地后新增占用约 **2.5~3 GB（全部在 D 盘，浏览器已计入 tools 目录）**，余量充足。

| 项目 | 位置 | 预估占用 | 说明 |
|---|---|---|---|
| Qwen3-Embedding-0.6B Q8_0 GGUF | `models\text\Qwen3-Embedding-0.6B\` | ~0.65 GB | F16 备选 ~1.2 GB，Q8 对检索质量影响可忽略 |
| Qwen3-Reranker-0.6B Q8_0 GGUF | `models\text\Qwen3-Reranker-0.6B\` | ~0.65 GB | 同上 |
| Python 依赖增量 | `D:\models\.venv\` | 0.3~0.5 GB | openai / mcp / playwright / sqlite-vec / pydantic / fastapi 等 |
| Playwright Chromium | `d:\models\tools\playwright-browsers\` | ~0.55 GB（含 ffmpeg ~0.8 GB） | PLAYWRIGHT_BROWSERS_PATH 重定向，不占 C 盘 |
| Agent 代码 + 配置 | `d:\models\agent\` | < 5 MB | — |
| 会话库 + 向量库（初期） | `agent\memory\` | < 50 MB | 随使用线性增长，万级文档约 0.5~1 GB |
| 输出产物 | `d:\models\output\agent\` | 按任务 | 沿用全局输出目录约定 |
| LiteLLM + 本地 Postgres（P3 可选） | `.venv\` + `tools\postgres\` | ~0.4 GB | RAM 常驻 +0.5~0.8 GB；token 记账/路由网关 |
| **D 盘合计** | | **~2.9~3.4 GB** | 含 Chromium 进 tools、监控层可选件；F16 备选方案上限 ~5 GB |
| 运行内存（RAM） | — | +1.5~2 GB | embedding/rerank 服务常驻 CPU 模式 |

## 6. 显存与内存调度

| 服务 | 显存 | 内存 | 策略 |
|---|---|---|---|
| Qwen3.6-35B（主脑，`--cpu-moe --load-mode none`） | ~4-5 GB | ~20 GB | 现有固化配置，agent 会话期间常驻 |
| Embedding/Reranker 0.6B ×2 | **0（`-ngl 0` 纯 CPU）** | ~1.5 GB | 0.6B 模型 CPU 足够快，为零显存压力刻意不进 GPU |
| Playwright | 0 | ~0.3 GB | 按任务启停，页面关闭即释放 |
| ComfyUI（生成工具触发时） | ~8 GB 独占 | — | 与对话模型、MOSS-TTS/ASR 互斥：工具调用时检测端口并提示手动停服（自动停/拉留待后续） |

## 7. 分阶段实施计划

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **P0 骨架** | loop + 文件/Shell/Python 沙箱 + 会话存储 + CLI | 10 步以内多工具任务（如"统计某目录文件并写报告"）稳定完成 |
| **P1 联网** | 搜索 + Playwright 浏览器 + RAG 三件套（下载 2 个 0.6B 模型 + sqlite-vec） | 5 个真实网页任务（含百度/知乎）成功率 ≥ 80%；本地 10 份文档问答命中 |
| **P2a 观测与自主规划** | 规划器（按成本选路线）+ JSONL 事件流 + 资源采样 + 本地看板 + 浏览器截图预览 | 任务前输出路线与成本；看板实时显示步骤框图/资源仪表/预览图 |
| **P2b 生成与语音** | ComfyUI 生成工具挂载、语音交互编排、定时任务、playwright-mcp 升级 | 语音对话闭环；"生成一张海报并配乐"级组合任务 |
| **P3 平台化（v5）** | VSCode + Roo Code 双轨接入、LiteLLM 网关、Prometheus 指标、Grafana 看板（可选） | Roo Code 内切换模型跑同一 MCP 工具集；每次调用的 token/延迟可查；GPU/RAM 曲线可见 |

> **P0 落地状态（2026-10-23）**：✅ 完成并通过验收——11 项单元测试全过；nanbeige 实机跑通「统计目录 `.py` 文件数与总行数并写报告」，5 轮 / 4 次工具调用 / 7923 token，结束原因为 `done`。
> 已落地文件：`agent\`（cli / loop / llm / context / router）、`agent\tools\`（registry / scope / proc / files / shell / sandbox）、`agent\memory\store.py`、`configs\agent.json`、`scripts\start_agent.bat`、`tests\`（test_tools + test_loop）。
> 与设计的差异：① `tools.json` 暂并入 `agent.json`（配置项少，拆分留到工具族增多时）；② 新增 `tools\scope.py` 与 `tools\proc.py` 承担路径边界与子进程处理；③ LLM 客户端用 openai SDK（已装入主 `.venv`），未新增独立环境。
> P0 用法：先启动任一模型服务（`scripts\llama_cpp\<模型>\start.bat`），再 `python -m agent.cli` 或双击 `scripts\start_agent.bat`。
>
> **P1 落地状态（2026-10-23）**：✅ 完成并通过验收——17 项单元测试全过；实机跑通「搜索进博会时间 → 浏览器开新闻页读正文 → 总结写报告」，报告见 `output\agent\p1_report.md`。
> 已落地：`tools\search.py`（必应/博查/DuckDuckGo 多源自动切换）、`tools\browser.py`（Playwright 7 个原子工具，Chromium 已装 `tools\playwright-browsers\`）、`memory\rag.py`（kb_ingest/kb_search/kb_stats 三工具）、`mcp_client.py`（stdio 短连接模式）、`scripts\start_embed_server.bat`。
> 新模型：`models\text\Qwen3-Embedding-0.6B\`（Q8_0，526MB，官方仓库）+ `models\text\Qwen3-Reranker-0.6B\`（Q8_0，767MB，**QuantFactory 社区仓库**——Qwen 官方未发布 Reranker 的 GGUF）。
> 与设计的差异：① 搜索默认源改**必应国内版**（实测 DuckDuckGo 被墙超时，博查留 key 接口）；② SearXNG 未自建（单机无 Docker）；③ 浏览器导航增加**崩溃自愈**（TargetClosedError 自动重建实例，首次验收时 ciie.org 超时曾把整实例打挂）；④ embedding/rerank 服务均 `-ngl 0` 纯 CPU（:8081/:8082）。
> 已知教训：验收任务首次选了不可检索的虚构标题导致 15 轮打满（130k token）——护栏按设计生效；agent 在网页检索失败时会自主回退查本地知识库（kb_stats），行为符合预期。
>
> **P2a 落地状态（2026-10-23）**：✅ 完成并通过验收——30 项单元测试全过；LFM 实机验证三项能力：①`--plan` 先输出路线与成本再逐步执行（任务「读配置列工具写报告」自动规划 2~4 步，plan 面板打印 `approach/reason/est_cost/steps`）；②看板 `http://127.0.0.1:8090` 实时显示步骤框图（pending/running/done/failed）、CPU/内存/显存/GPU 四表、事件流；③`browser_open` 每步自动截图到 `output\agent\preview\latest.png`，看板 `/preview.png` 可直接查看（实测 38KB PNG）。
> 已落地：`agent\planner.py`、`agent\trace.py`（JSONL + psutil/nvidia-smi 采样，5MB 轮转）、`agent\monitor.py`（标准库 HTTP，`/`、`/state`、`/preview.png`、`/trace.jsonl`）、`tools\browser.py` 截图钩子、`loop.py` 事件埋点、`configs\agent.json` 的 `monitor.port` 与 `paths.preview/trace`。
> 用法：`python -m agent.cli --task "..." --plan`（自动开看板）；交互模式内 `/plan on|off` 切换、`/monitor` 打开看板。单步轮数上限 8（防止小模型在一步里反复重试），规划失败自动回退单步直执行。
> 与设计的差异：看板未用 FastAPI/WebSocket（标准库 + 1 秒轮询足够）；自主规划只在**已实现工具**内选路线，不承诺模型发明新能力。
> 同时修复：`tools\shell.py` 的命令切分改为**引号感知**——此前 `python -c "import x; ..."` 会被分号切断并误判首词（`data`/`import`），导致合法命令被拒。
>
> **P2b 落地状态（2026-10-23）**：✅ 生成与语音工具已完成并通过验收——42 项单元测试全过。新增 `tools\comfy.py`（`comfy_status` / `generate_image` / `generate_video` / `generate_music`，子进程复用 `scripts\comfyui\run_*.py`，长任务超时 15/60/20 分钟，启动前检测 :8188 与 :8080 显存互斥并提示）、`tools\voice.py`（`tts_speak` 文本→wav，可给参考音频克隆音色；`asr_transcribe` 音频→分段文本 + 说话人 + JSON/SRT）。实机验收：ComfyUI 文生图 768x512 用时 35s（产物 `output\agent\generated\image\...png`）；TTS 合成 23s（`output\agent\audio\tts_tool.wav`）后 ASR 转写 13s，4 段全部命中；LFM2.5 通过 agent loop 正确调用 `comfy_status` 并汇报。
> 用法：先起 ComfyUI（`scripts\comfyui\start_comfyui.py`）再用 `generate_image` 等；语音模型与 ComfyUI 显存互斥，需先后顺序执行。生成/语音产物统一进 `output\agent\`（`generated\`、`audio\`）。
> 顺带修复 `scripts\other\tts_moss.py` 与新版 transformers 4.57 的三处不兼容：`transformers.initialization` 被移除、RoPE 只认 `rope_scaling`、`create_causal_mask` 参数改回 `input_embeds + cache_position`——均在脚本内做运行时兼容，不改模型文件。
> 与设计的差异：未实现"生成前自动停 llama-server、完成后自动拉起"（P2b 先由工具给出显存提醒，自动化留给后续）；定时任务已内置在 WebUI 中。
>
> **Playwright MCP 落地状态（2026-10-24）**：✅ 已本地安装并接入 `mcp_client.py`。`@playwright/mcp@0.0.83` 装在 `d:\models\tools\mcp-servers\playwright-mcp`（符合 v4「第三方工具不进 agent 目录」约定），复用系统 Edge（`--browser msedge`，无需下载 Chromium）。`mcp_client.py` 新增 **persistent 常驻会话**模式：同一子进程 + 同一浏览器跨工具调用保持页面状态（实测 navigate → snapshot → click → snapshot 后 URL 正确跳转）；未标 `persistent` 的 server 仍走短连接。WebUI 启动时也会挂载 MCP（此前只有 CLI 会挂）。顺带修复新版 mcp SDK `input_schema` 字段名不兼容导致的 `list_tools` 崩溃。
>
> **P2c + P3 落地状态（2026-10-23）**：✅ 定时任务、Web UI、Prometheus 指标已完成——54 项单元测试全过。新增 `agent\scheduler.py`（标准库实现，支持 once/interval/daily 三种触发，JSON 持久化，后台线程 30s 检查）、`tools\schedule.py`（`schedule_task` / `list_scheduled` / `cancel_scheduled` 三工具）、`agent\webui.py`（轻量 Web 聊天界面，标准库 http.server，:8088，支持会话列表/消息加载/发送任务）、`monitor.py` 新增 `/metrics` 端点（Prometheus 格式，从 SQLite 读取 runs/rounds/tokens/sessions）。playwright-mcp 已于 2026-10-24 升级接入（见上，常驻会话模式）；LiteLLM 未部署：本机单模型常驻场景下其自动路由/回落价值不大，token 记账已由 SQLite + /metrics 承担。用法：`--scheduler` 启动调度器、`--webui` 启动聊天界面；**运行看板（:8090，含 `/metrics`）现在默认随启动开启**，不需要再加 `--monitor`，用 `--no-monitor` 可关闭。
> 待做：无（P0~P3 全部落地）。
>
> **调度架构优化（规划中，2026-10-24）**：针对"所有任务都用最强模型、全程串行"的时效问题，已形成独立方案 [调度架构方案.md](调度架构方案.md)，核心是模型分层（S/A/B/C 按步骤复杂度选用）+ DAG 资源标注 + GPU 主槽/CPU 池双资源池调度 + 监视器多任务视图。建议先落地 P1（模型分层，半天工作量）验证提速后再推进。

## 8. 与现有资产的衔接

- `scripts\llama_cpp\models.json`：路由表直接读取各模型最优启动参数，不重复维护
- `scripts\comfyui\comfy_client.py`：已包装为 `generate_image/video/music` 工具（子进程复用 `run_*.py`，含模型名自动校正与长时间等待）
- Craft MCP：`mcp_client.py` 沿用已验证的绝对路径调用与"关闭思考链"约定
- 工具层第三方组件（MCP server、Chromium）安装到全局工具根目录 `d:\models\tools\`，与 Craft 工具链同根管理
- 输出统一 `d:\models\output\agent\`；.bat 入口放 `agent\scripts\`，纯 ASCII 注释；如写 PowerShell 脚本必须带 UTF-8 BOM
- 新模型下载走 ModelScope 优先、hf-mirror 兜底，模型目录按现有扁平命名规范放 `models\text\`

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| Qwen3.6 长上下文（>16K）速度下降 | loop 内历史裁剪 + 工具结果摘要化；agent 会话默认 ctx 16K |
| 国内网站反爬/验证卡死浏览器 | Playwright 原子工具带单步超时；连续 2 次失败即上报用户，不死循环 |
| Python 沙箱误删文件 | 沙箱固定临时目录 + 环境变量隔离；Shell 工具默认白名单命令 |
| ComfyUI 与 35B 显存互斥 | 生成工具入口自动检测/切换进程，失败则提示手动处理 |
| sqlite-vec 单文件并发写 | 单进程 agent 串行写即可，无并发需求 |
| Roo/Cline 对 30B 级模型 tool-call 格式退化、循环卡死（社区已知） | 启用 Compact Prompt + 限制单任务步数 + 关闭 auto-approve 改审批制；关键任务绑 qwen36 profile |
| LiteLLM/Postgres 常驻挤压 RAM（35B 已占 ~20GB） | 按需启停网关进程；不部署 Langfuse；Postgres shared_buffers 压至 128MB |

---

## 10. 全量实施预估（v2：按能力栈全盘落地）

> 第 7 节为渐进路线；本节评估把第 2 节架构图中全部"待补齐"项 + 感知层编排全部做完的总账。代码量为量级估计（±30%）。

### 10.1 模块拆解与代码量

| # | 模块 | 交付内容 | 预估代码量 | 新增依赖 |
|---|---|---|---|---|
| 1 | loop.py 主循环 | tool-call 循环、护栏（轮数/超时/重试） | ~350 行 | — |
| 2 | context.py | 历史裁剪、工具结果摘要、中途压缩 | ~180 行 | — |
| 3 | llm.py + router.py | 端点客户端、主脑/轻任务/视觉路由 | ~250 行 | openai |
| 4 | tools 基础四件套 | files / shell / sandbox / registry | ~470 行 | — |
| 5 | search.py | SearXNG/博查适配 | ~100 行 | httpx |
| 6 | browser.py | Playwright 6 个原子工具 | ~300 行 | playwright |
| 7 | mcp_client.py | stdio MCP 接入（Craft/其他 server） | ~150 行 | mcp |
| 8 | memory/store.py | SQLite 会话/任务状态/长期记忆 | ~150 行 | — |
| 9 | memory/rag.py | 切片、向量化、召回、精排 | ~300 行 | sqlite-vec |
| 10 | 文档解析入库 | PDF/DOCX/TXT/MD → 文本切片 | ~200 行 | pymupdf、python-docx |
| 11 | comfy.py 生成工具 | 文生图/视频/音乐三工具 + 显存自动切换 | ~200 行 | — |
| 12 | voice.py 语音编排 | silero-vad + Qwen3-ASR + MOSS-TTS 闭环 | ~250 行 | — |
| 13 | 子 Agent / 并行 | 任务拆分 + llama-server 并行槽 | ~200 行 | — |
| 14 | scheduler.py | APScheduler 定时/主动任务 | ~100 行 | apscheduler |
| 15 | computer use（实验） | pyautogui + Qwen2.5-VL grounding | ~200 行 | pyautogui |
| 16 | Web UI | FastAPI + 单页前端（会话/工具开关） | ~600 行 | fastapi、uvicorn |
| 17 | cli.py + configs | 交互入口与配置体系 | ~250 行 | — |
| 18 | tests | 工具单测 + 10 个端到端任务集 | ~500 行 | pytest |
| | **合计** | | **~4700 行** | 依赖增量 ~0.1 GB |

### 10.2 资源总账（全量 vs v1）

| 维度 | v1（P0+P1） | 全量 | 说明 |
|---|---|---|---|
| D 盘新增 | ~2.5~3 GB | **~3.3~3.8 GB** | Chromium 已随 tools 目录计入 D 盘 |
| C 盘新增 | 0 | 0 | 浏览器改存 `d:\models\tools\`，C 盘零占用 |
| 新模型下载 | 2 个 0.6B | **仍是 2 个 0.6B** | 语音/视觉/生成全部复用已有模型 |
| RAM 增量 | +1.5~2 GB | +2~2.5 GB | 35B(~20GB) + embed/rerank(1.5GB) + 并行槽 KV，32GB 内可承载 |
| 显存 | 35B 常驻 4~5 GB | 同左 | TTS / ComfyUI 触发时走互斥切换 |
| 并行槽 | 单槽 | `-np 2~4` | KV cache 显存随槽位线性增长，8GB 下建议 -np 2 |

### 10.3 开发-验证轮次预估

按本项目协作模式（我写代码 → 你运行 → 我读日志修正）估算，每轮为一次完整迭代，非日历时间：

| 阶段 | 模块 | 轮次 | 主要不确定性 |
|---|---|---|---|
| P0 骨架 | #1-4、17 | 3~5 轮 | 工具 schema 与裁剪策略调参 |
| P1 联网 + RAG | #5-10 | 6~9 轮 | 浏览器反爬/验证码、检索质量调参 |
| P2 体验 | #11-16、18 | 8~12 轮 | 显存自动切换、语音实时性、Web UI 联调 |
| **合计** | | **17~26 轮** | — |

### 10.4 全量风险与裁剪建议

| 项 | 风险 | 建议 |
|---|---|---|
| computer use（#15） | Qwen2.5-VL-7B grounding 精度有限，误点率高 | 降级为实验特性，最后做，可砍 |
| Web UI（#16） | 纯体验项，工作量占 P2 一半 | 放最后；CLI 稳定前不动 |
| 子 Agent 并行（#13） | 8GB 显存并行槽吃紧 | 先 -np 2 验证收益，无收益则回退串行 |
| 语音全双工 | VAD 抢话、TTS 出声延迟 | 先做 push-to-talk 半双工，稳定后再考虑全双工 |
| 浏览器 | 国内站点反爬/验证码 | 白名单站点起步 + 连续失败上报机制 |

**裁剪后最小全量**（砍 #15、Web UI 缓做、语音半双工）：约 3900 行、17~22 轮，仍覆盖架构图全部核心缺口。
**（v5 增补）**：交互式 UI 由 Roo Code 路线承担后，#16 Web UI（~600 行）进一步缓行；监控层为配置型工作（非开发），不占代码量，全量 D 盘按 ~3.7~4.2 GB 计。

---

**版本记录**
- v5（2026-10-22）：新增 3.5 平台层选型，架构升级双轨制——交互主力轨 VSCode + Roo Code（MCP Marketplace / Profiles 模型切换 / per-task token 统计，2026-10 现状调研核实），自动化引擎轨保留自研 loop（可平移 PydanticAI v2），监控层 LiteLLM（pip 免 Docker）+ llama-server --metrics + ComfyUI /system_stats；Dify/OpenHands/LibreChat/Langfuse/Agno 经评估不采用（Docker 依赖或资源过重），AnythingLLM 留作 RAG 备选；新增 P3 平台化阶段与对应风险对策
- v4（2026-10-22）：工具层安装位置修正——第三方组件（MCP server、Chromium）从 agent\tools\ 改为全局工具根目录 d:\models\tools\（与 Craft 同根），agent 目录内不再设 tools 安装目录
- v3（2026-10-22）：目录重构——新增顶层 `tools\`（MCP server/浏览器等第三方工具层组件统一安装，PLAYWRIGHT_BROWSERS_PATH 重定向）与顶层 `memory\`（session.db / vectors.db / 长期记忆快照集中存储，替代原 data\）；D 盘总量上调至 2.5~3 GB，C 盘零占用
- v2（2026-10-22）：新增第 10 节全量实施预估——18 个模块 ~4700 行、D 盘 2.5~3 GB、17~26 开发-验证轮次、风险裁剪建议
- v1（2026-10-22）：初版方案，框架选型自研 loop + Playwright + sqlite-vec，空间预估 ~2.2 GB（D 盘）
