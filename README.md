# D:\models 本地 AI 工作站

单卡 RTX 5060 Laptop（8GB VRAM / Blackwell sm_120）+ 32GB RAM 上的本地推理与生成环境。
核心思路：**用内存换显存**——MoE 专家层卸载到 CPU、GGUF 量化、KV cache 量化，让 8GB 显存跑动 35B 级模型与视频/音乐/语音生成。

> **仓库说明**：本仓库只收录自研代码、配置、文档与测试结果。模型权重（`models/` 下除 `README.md`）、`.venv`、第三方运行时（ComfyUI / llama.cpp / tools）及大体积音视频产物均不入库，按 `models/README.md` 与各目录 README 自行下载安装。

| 引擎/链路 | 用途 | 入口 |
|---|---|---|
| llama.cpp（自编译 CUDA） | 文本/多模态推理，OpenAI 兼容 API | `scripts\llama_cpp\` |
| ComfyUI + ComfyUI-GGUF | 视频（MiniMax H3）、音乐（ACE-Step）、文生图 | `scripts\comfyui\` |
| VoxCPM2（pip install voxcpm） | 语音合成 + 音色克隆 / Voice Design | `scripts\other\tts_run.py` |
| MOSS-Music-8B（4bit NF4） | 音乐生成质检 | `scripts\other\music_qc.py` |
| FunASR + Qwen3-ASR | 语音转写 + 说话人分离 | `scripts\other\asr_diarize.py` |
| 云端 Strata（内网 vLLM） | 对比基准 / 云端大脑 | `scripts\strata\` |

---

## 目录结构

```
D:\models\
├── llama.cpp\                    # 源码 + build\bin\Release 产物（CUDA 13.2 + sm_120 编译）
├── ComfyUI\                      # ComfyUI 主程序 + custom_nodes\ComfyUI-GGUF
│   ├── extra_model_paths.yaml    # 模型路径映射 → D:\models\models
│   └── output\                   # 生成的视频/音乐输出
├── models\                       # 模型库（按业务领域归类，详见 models\README.md）
│   ├── text\                     # 文本/多模态 GGUF：Qwen3.6-35B / Qwen2.5-VL-7B
│   │                             #   MiniCPM-V-4.6 / LFM2.5-8B-A1B / Nanbeige4.2-3B
│   ├── rag\                      # 检索增强：Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B（Q8_0）
│   ├── agent\                    # 桌面操控：Mage-VL-Cowork（32B，NF4，权重待下载）
│   ├── video\                    # MiniMax-H3（FL2VA int8 主力；Wan2.2 全链路已清理）
│   ├── music\                    # ACE-Step-1.5（音乐生成）+ MOSS-Music-8B（音乐质检）
│   ├── image\                    # 文生图：Anima / ERNIE-Image-Turbo / Z-Image（+ diffusion_models/encoder/vae）
│   └── audio\                    # 转写分离：Qwen3-ASR-0.6B + Qwen3-ForcedAligner-0.6B + campplus + fsmn-vad
│                                 #   VoxCPM2（TTS）经 pip 安装，不存模型目录
├── scripts\                      # 全部脚本（详见 scripts\README.md 与下方脚本一览）
│   ├── llama_cpp\                # 5 款模型独立目录（start.bat + 最优参数 models.json）+ runner
│   ├── comfyui\                  # ComfyUI 启动 + 视频/音乐/文生图提交客户端
│   ├── other\                    # tts_run（VoxCPM2）/ asr_diarize / music_qc / mage_cowork
│   ├── strata\                   # 云端 Strata 调用样例 + bench\ 基准脚本
│   └── config.py                 # 全局路径与公共配置
├── docs\                         # 测试报告 + Strata 部署文档 + bench 原始数据 + Craft 资料（README.md 为索引）
├── sample\                       # 端到端演示项目
│   └── 铁锈海的女儿\             # 小说→分镜→文生图→图生视频→配音/BGM 全链路案例
├── agent\                        # 本地 Agent 项目（v5 设计 + P0~P3 全部落地：自研 loop + 工具集 + 规划/看板 + 生成/语音 + 定时任务 + Web UI + 指标）
├── tools\                        # 全局工具根：storytold-ArtCraft（Craft 家族）、mcp-servers、playwright-browsers
├── output\                       # 统一输出目录
├── .venv\                        # uv 环境（复用系统 torch 2.14.0+cu130）
├── local-models-environment.md   # 本地模型运行环境手册
└── comfyui_diffusion_node_pipeline.html
```

---

## 一、文本与多模态推理（llama.cpp）

每款模型一个独立目录，双击 `scripts\llama_cpp\<模型>\start.bat` 即按最优参数启动；也可用 `scripts\llama_cpp\start_server.py` 统一拉起。模型注册表 `scripts\llama_cpp\models.json`。

| 标签 | 模型 | 定位 | 实测结论 |
|---|---|---|---|
| `qwen36` | Qwen3.6-35B-A3B | 全能旗舰（多模态 VLM） | 写作/推理/编程/工具调用全部第一，~39 tok/s |
| `minicpmv` | MiniCPM-V-4.6 | 图生文主力（OCR/描述） | 体积小加载快，文本能力弱 |
| `qwen25vl` | Qwen2.5-VL-7B | 图表/版面理解备选 | ~65 tok/s，文本能力一般 |
| `lfm` | LFM2.5-8B-A1B | 极速对话/轻量 agent | ~222 tok/s，工具调用最干净 |
| `nanbeige` | Nanbeige4.2-3B | 快速轻量任务 | 写作/摘要 4.5/5，工具调用 3/3 |

- 已删除（2026-10-20，被上表覆盖）：LFM2-24B、Ornith-9B、DeepSeek-R1-8B，理由见 `scripts\llama_cpp\README.md`
- 已删除（2026-11-08，省 21.1 GB）：Nemotron-3-Nano-Omni-30B-A3B，测试结果保留在 `docs\bench_results\nemotron*\` 与测试报告
- MoE 30B/35B 级统一 `--cpu-moe --load-mode none` 专家层内存常驻；KV cache 量化仅长上下文场景启用
- **测试报告**（推理/编程/英文/云端对比/工具调用）在 `docs\`；专项 runner：`run_reasoning.py`、`run_coding.py`、`run_en_bench.py`，速度基准 `bench.py`

---

## 二、视频 / 音乐 / 文生图（ComfyUI）

```powershell
uv run python scripts/comfyui/start_comfyui.py    # --lowvram --cache-classic，端口 8188
```

| 链路 | 模型 | 提交入口 |
|---|---|---|
| 图生视频 | MiniMax-H3 FL2VA int8（video\ 唯一主力） | `scripts\comfyui\run_video.py` |
| 音乐生成 | ACE-Step-1.5（safetensors，核心原生支持） | `scripts\comfyui\run_music.py` |
| 文生图 | Anima / ERNIE-Image-Turbo / Z-Image | `scripts\comfyui\run_image.py` |

- `comfy_client.py` 含模型名自动校正（拉取 /object_info 可用清单，自动转换工作流内文件路径）
- 工作流 JSON 按工具归档在 `scripts\comfyui\<工具>\`
- **音乐质检闭环**：ACE-Step 生成 → `scripts\other\music_qc.py`（MOSS-Music-8B 4bit）以调性/配器/情绪/时长为主判据
- **显存互斥**：ComfyUI（≈8GB 独占）与 MOSS-Music（≈6GB 独占）不可同时运行，切换前先停对方进程

---

## 三、语音合成与转写分离

```powershell
uv run python scripts/other/tts_run.py --text "你好" --out D:\models\output\hi.wav           # Voice Design：括号描述音色
uv run python scripts/other/tts_run.py --text "你好" --voice ref.wav --out D:\models\output\hi.wav  # 参考音频克隆
uv run python scripts/other/asr_diarize.py <音频> --align        # 转写+说话人分离+字级时间戳
```

- **合成**：VoxCPM2（2B，Apache-2.0，pip 安装），内置 AudioVAE V2，48kHz 输出，30 语种 + 9 种汉语方言；支持 Voice Design（无参考音频，括号描述音色）、可控克隆、终极克隆
- **转写分离**：FunASR + Qwen3-ASR-0.6B 转写，Qwen3-ForcedAligner-0.6B 字级对齐，campplus 声纹嵌入 + KMeans 聚类分说话人，fsmn-vad/silero-vad 分段；仅出 SRT 可跳过声纹聚类
- 已清理：MOSS-TTS + MOSS-Audio-Tokenizer（需外置 tokenizer、24kHz、不可商用、生成需参考音频、人声情感把握欠缺，保留为备选）、faster-whisper、pyannote

---

## 四、Agent 与工具生态

- **`agent\`**：本地 Agent 项目，`agent\README.md` 为 v5 设计方案（双轨制：VSCode + Roo Code 交互轨 / 自研 loop 自动化轨 + LiteLLM 监控层）。**P0~P3 全部落地**（2026-10-23）：`python -m agent.cli` 即可用；工具含文件四件套 / 受限 Shell / Python 沙箱 / 联网搜索（必应为主源）/ Playwright 浏览器 / 知识库（kb_ingest/kb_search，向量检索用 Qwen3-Embedding-0.6B + Reranker-0.6B，CPU 服务 :8081/:8082）/ ComfyUI 生成（`generate_image`/`generate_video`/`generate_music`）/ 语音（`tts_speak` 合成 + `asr_transcribe` 转写与说话人分离）；会话与 token 账本存 `agent\memory\session.db`。P2a 新增：`--plan` 自主规划路线与成本、运行看板 `http://127.0.0.1:8090`（步骤框图 + CPU/内存/显存/GPU 仪表 + 事件流）、浏览器每步截图预览（`output\agent\preview\latest.png`）。P2b 生成/语音产物落 `output\agent\generated\`、`output\agent\audio\`，ComfyUI 与语音/对话模型显存互斥需先后启动。P2c 新增：`--scheduler` 定时任务调度（once/interval/daily，`schedule_task`/`list_scheduled`/`cancel_scheduled` 工具，JSON 持久化）、`--webui` 轻量 Web 聊天界面 `http://127.0.0.1:8088`（标准库 http.server，会话列表 + 工具事件展示）。P3 新增：看板 `/metrics` 端点输出 Prometheus 指标（runs/rounds/token/会话数，取自 SQLite 账本）；playwright-mcp 与 LiteLLM 经评估**不实施**（browser.py 已稳定、单模型常驻下网关无价值，决策详见 agent\README.md）。第三方工具组件统一装 `tools\`
- **`tools\storytold-ArtCraft\`**：Craft 家族应用（wordcraft/deckcraft/filmcraft 等 15+ 便携 exe），MCP 调用方法见 `ai-agent\MCP调用教程.md`，代理脚本 `craft_agent.py`；本地模型工具调用实测见 `docs\工具调用测试报告.md`
- **`tools\mcp-servers\`**：为 agent 预置的 MCP 工具层（待装）；**`tools\playwright-browsers\`**：Chromium 已装（P1 浏览器工具使用）

---

## 五、样例项目：铁锈海的女儿

`sample\铁锈海的女儿\`——小说→分镜→文生图→图生视频→配音/BGM 的端到端全链路样例，目录自包含（含全部脚本、工作流、分镜数据、成片与测试产物），详见其 README.md。视频链路最终仅保留 MiniMax H3 int8 版本。

---

## 六、模型下载与维护

```powershell
uv run python scripts/download_models.py --list        # 文本模型仓库文件列表
uv run python scripts/download_models.py               # 文本模型（断点续传+跳过已存在）
uv run python scripts/download_video_models.py         # 视频/音乐/语音模型
```

- 下载走 hf-mirror.com 镜像（脚本内置）；**ModelScope 稳定性更优**，大模型优先走 ModelScope
- 断点续传勿混用不同来源（拼接会损坏），不完整文件删除重下
- 新增模型：在下载脚本的 JOBS 表加 `(标签, 仓库, 文件, 目标目录)` 四元组；目录规则：gguf 平铺在模型名目录，扩散模型建 `diffusion_models\` 子目录

---

## 七、云端 Strata 与文档索引

- **云端调用**：`scripts\strata\strata_client.py`（对话/流式/多模态封装，双击 `run_chat.bat` 验证），端点 <strata-host>:8082，部署/密钥/局域网文档在 `docs\strata\`
- **基准脚本**：`scripts\strata\bench\bench_*.py`（universal/coding/reasoning），结果写入 `docs\bench_results\`
- **测试报告**（`docs\README.md` 有完整索引）：云端vs本地对比、推理能力、编程能力、英文基准、工具调用测试

---

## 八、脚本一览

| 脚本 | 作用 |
|---|---|
| `config.py` | 全局路径与公共配置（llama-server 产物路径等） |
| `llama_cpp\start_server.py` / `bench.py` | 模型拉起 / tok/s 与显存基准 |
| `llama_cpp\run.py` / `vlm_test.py` | 对话测试 / 多模态测试 |
| `llama_cpp\run_reasoning.py` 等 | 推理/编程/英文基准 runner（调 bench_*.py） |
| `comfyui\start_comfyui.py` | ComfyUI 启动 |
| `comfyui\run_video.py` / `run_music.py` / `run_image.py` | 工作流提交 + 轮询取结果 |
| `other\tts_run.py` | VoxCPM2 语音合成（Voice Design / 参考音频克隆） |
| `other\asr_diarize.py` | 转写 + 说话人分离 |
| `other\music_qc.py` | MOSS-Music 音乐质检 |
| `mage_cowork\mage_infer.py` / `mage_config.py` | Mage-VL-Cowork 桌面操控推理层与配置 |
| `strata\strata_client.py` | 云端 Strata 调用封装 |
| `strata\bench\bench_*.py` | 云端/本地基准测试 |
| `download_models.py` / `download_video_models.py` | 模型下载（镜像+续传） |

## 九、环境要点

- **Python**：uv 管理（`.venv`），`pyvenv.cfg` 已设 `include-system-site-packages = true`，复用系统 torch 2.14.0+cu130 / torchvision 0.29.0 / torchaudio 2.11.0，**不要在 venv 里重装 torch**
- **pip**：全局已配清华源
- **llama.cpp**：CUDA 13.2 + sm_120 专用编译，重编译用 `cmake --build build --config Release`
- **镜像**：HF → `hf-mirror.com`；GitHub → `ghfast.top` 前缀
- **输出位置**：视频/音乐 → `ComfyUI\output\`；语音等 → `D:\models\output\`
- **显存调度**：ComfyUI 与 MOSS-Music 互斥；35B/30B MoE 依赖 RAM 常驻（约 20GB），与两者先后切换