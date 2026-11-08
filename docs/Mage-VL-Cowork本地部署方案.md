# Mage-VL-Cowork 本地部署调研与实测结论

> 调研：2026-11-03　实测：2026-11-04
> 本机基线：RTX 5060 Laptop 8GB / RAM 34GB / Windows 10 Home / D 盘剩余 46GB / WSL2 Ubuntu 24.04

---

## 一、结论先行

| 目标 | 结论 | 依据 |
|---|---|---|
| 本地跑通推理 | **可以**：4bit NF4，8GB 显存占用约 4.4GB | 实测加载零缺失、单次生成 1–2 秒 |
| 本地做 GUI 自主执行 | **不可用**：已放弃 | 四轮实测，模型看得见界面但决策退化，反复套 GNOME 先验 |
| 推荐形态 | 云端 SGLang BF16（≥16GB 显存）做正式任务 | 官方推荐路径，本机 8GB 装不下 BF16 |
| 本机可用定位 | **bash 通道执行员**：命令级任务，不用它看图点按钮 | bash 能力在训练分布内且实测可用 |

**一句话结论**：4bit 量化保留了视觉识别，但打坏了「看图→决策」这一步。本机方案只保留推理与命令行执行，GUI 自动化交回云端 BF16 或人工。

---

## 二、它是什么（关键事实）

| 项目 | 规格 |
|---|---|
| 发布 | 2026-10-30，Microsoft Mage Team，Apache-2.0 |
| 参数 | 4B（Hub 元数据 4.74B），`llava_onevision2` 架构 |
| 底座 | Mage-ViT + Qwen3-4B-Instruct-2507 |
| 权重 | BF16 9.48GB（2 个 safetensors 分片） |
| 上下文 | 活跃窗口 32768（架构上限 262144，不要开满） |
| 记忆策略 | 非对称滑窗：最近 3 张截图 + 4 条完整回复，更早折叠为 `Action:` 摘要 |
| 动作通道 | `computer_use`（11 个 GUI 原语，坐标归一化 [0,999]）+ `bash`（持久 shell/Python） |
| 输出格式 | `<think>…</think>` + 单行 `Action:` + `<tool_call>…</tool_call>` |
| 成绩 | OSWorld-Verified 66.0%（361 任务、50 步预算、Ubuntu 22.04 GNOME） |
| 官方推理 | SGLang 0.5.2 + PyTorch 2.8.0+cu128，镜像 `xiaoyizhang/mage-vl-cowork:0.1.0` |

**必须遵守的三条硬约束**：
1. 系统提示词 `MAGE_HYBRID_SYSTEM_PROMPT` 不能省，工具 schema 与回复格式都在里面。
2. 采样参数：`temperature=0.7`、`top_p=0.8`、`max_new_tokens=4096`。
3. 模型卡要求跑在隔离容器/VM，不挂载宿主机凭据、SSH key、浏览器 cookie；它带 bash 通道，网页注入对它就是「更多像素」。

---

## 三、配置方案（调研结论）

### 方案 A：云端 SGLang 全精度（正式任务）

适用：≥16GB 显存的机器/实例。

```
docker run --gpus all -p 30000:30000 \
  xiaoyizhang/mage-vl-cowork:0.1.0 \
  python -m sglang.launch_server \
    --model-path microsoft/Mage-VL-Cowork \
    --trust-remote-code --dtype bfloat16 \
    --context-length 32768 --port 30000
```

要点：
- 设 `SGLANG_MAX_PIXELS=4000000`，保证 1920×1080 截图不被过度缩放（grounding 依赖细节）。
- 现有 vLLM 服务不能复用：`llava_onevision2` 是自定义架构，vLLM 未验证；必须独立 SGLang 实例。
- 客户端用官方 `POST /generate`（image_data 传截图），不要套 OpenAI 兼容层。

### 方案 B：本机 4bit（8GB 显存档，实测可用）

| 项 | 取值 | 说明 |
|---|---|---|
| 量化 | NF4，`bnb_4bit_compute_dtype=bfloat16` | 权重约 3GB |
| 上下文 | 8K–12K | 32K KV 约 4.8GB，8GB 卡必炸 |
| 输入分辨率 | 长边缩到 1920×1080 再送模型 | 与训练分辨率一致，grounding 最准 |
| 显存占用 | 加载期约 4.4GB，生成后回落到 ~640MiB | 实测值 |
| 依赖 | `transformers==4.57.3` | **必须降级**，见 4.3 |

两条子路线的风险对比：

| 路线 | 权重 | 显存估算 | 风险 |
|---|---|---|---|
| Transformers + bitsandbytes NF4 | ~3GB | 权重 3GB + 12K KV ~1.8GB ≈ 5–6GB | 中：自定义 remote code，需 `trust_remote_code=True`；4bit 后决策能力退化（本次实测证实） |
| Q4_K_M GGUF + mmproj（fork llama.cpp） | 2.72GB + 0.35GB | ~4.5GB（12K 上下文） | 高：需专用分支；上游 PR 未合并；stock llama.cpp / Ollama / LM Studio 未验证该 projector |

### 方案 C：不推荐

- `ollama run hf.co/.../Mage-VL-Cowork-GGUF:Q4_K_M`、LM Studio：官方与 GGUF 作者均未验证 projector，grounding 不可信。
- Windows 原生 bash 通道：模型在 Linux 终端语料上训练，bash 通道应落到 WSL2 / Linux，否则分布外。

### 目录与落地位置

```
d:\models\models\agent\mage-vl-cowork\      # 权重（BF16 两分片，9.48GB）
d:\models\scripts\mage_cowork\              # 推理层与配置
d:\models\output\mage_cowork\               # 实测截图与轨迹
```

下载（国内走镜像，HF 直连会超时）：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
hf download microsoft/Mage-VL-Cowork --local-dir d:\models\models\agent\mage-vl-cowork
```

> 注意：`huggingface-cli` 的 `snapshot_download` 容易触发 resolver 配额（100K 请求），大文件建议用 `curl` 直链 + `-C -` 断点续传。

---

## 四、本机实测结果（2026-11-04）

### 4.1 环境

| 组件 | 版本 | 状态 |
|---|---|---|
| Python | 3.12.10 | OK |
| torch + CUDA | 2.14.0+cu130 | OK |
| bitsandbytes | 0.50.2 | OK（NF4 / CUDA / bfloat16 均可用） |
| transformers | **4.57.3** | 必须用这个版本 |
| 权重 | 4352 + 4692 MB，两分片 | 696 tensors，全 BF16，头部校验通过 |
| WSL | Ubuntu 24.04.5 | xrdp 会话，display `:10`，会话分辨率 2560×1440 |

### 4.2 推理可行性：通过

一次真实截图输入：`patch_positions` = 8160 patches，输入 3186 tokens，单次生成 1–2 秒，显存峰值约 4.4GB。

输出格式完整：

```
<think>…</think>
Action: …
<tool_call>{"name": "computer_use", "arguments": {"action": "screenshot"}}</tool_call>
```

系统提示词注入、chat template、工具调用解析全链路正常。

### 4.3 踩到的三个坑（均已解决）

| 问题 | 根因 | 处置 |
|---|---|---|
| 36 层 LLM 权重全部 MISSING（随机初始化） | transformers ≥5.x 对该模型 `_checkpoint_conversion_mapping` 的嵌套 key 重映射不生效，checkpoint 是 `model.layers.*`，模型要 `model.language_model.*` | 降级到 `transformers==4.57.3` → 权重 100% 匹配 |
| `mm_token_type_ids` 不被 forward 接受 | 新版 Qwen2.5-VL processor 多吐一个字段 | 传入前 pop 掉 |
| `patch_positions` is None → AttributeError | 模型视觉侧强制要求，但 README 的 Transformers 示例没传（官方主推 SGLang，这条路径不完整） | 由 `image_grid_thw` 按 (t,h,w) 行主序用 `cartesian_prod` 生成并注入 |

### 4.4 GUI 自主执行验收：不通过

**Windows 设置页（原生 W1，3 次）**

| 轮次 | 模型动作 | 坐标 (1920×1080) |
|---|---|---|
| 1 | 正确识别为 Settings Colors page | — |
| 2 | "Click the Settings button" | (52, 13) |
| 3 | "top-right system menu"（自称 Ubuntu 桌面） | (1838, 13) |
| 4 | "return to the main Settings sidebar" | (586, 49) |

目标控件实在 (1371, 157)，误差最大 Δx≈785px。三次全部落在标题栏/面包屑，从未进入页面内容区。

**W3 Ubuntu xrdp 会话（8 步完整任务）**

- 任务：从 Applications 菜单打开 Terminal Emulator
- 事实：菜单**当时就开在屏幕上**，`Terminal Emulator` 清晰可见
- 结果：8 步全部说「点击 Show Applications 按钮 / GNOME overview」，一次也没点中菜单项；最终停在桌面背景，无窗口打开

**W3 显式指令（菜单已开，直接点 Terminal Emulator）**

仍然先点「Show Applications」，第 4 步输出开始语法崩坏，并出现成段重复的 `<think>` 块。

### 4.5 决定性诊断：视觉没坏，决策坏了

让模型**只读图、不做决策**，描述同一张截图：

- 正确读出全部菜单项：Run a Command / Terminal / File Manager / Mail Reader / Web Browser / Settings / Accessories / Media / System / Log Out
- 仅个别字误（`About Xce`），整体 OCR 可用

结论：4bit 量化保留了视觉识别能力，退化发生在「看图→决策」这一步——它读到了内容，仍按 GNOME 模板行动。

### 4.6 基础设施可用性（与模型能力无关，实测均通过）

| 能力 | 状态 |
|---|---|
| xrdp 会话截屏（`scrot`，display `:10`） | 通过，2560×1440 真实画面 |
| 键鼠注入（`xdotool`） | 通过，指针实测从 (2555,725) 移到 (90,22)，菜单正常弹开 |
| 坐标换算（`[0,999]` → 屏幕像素，分母 999） | 通过 |
| bash 通道落到 WSL2 | 通过 |

即「能不能操作电脑」这一层没有问题，卡住的是模型决策。

---

## 五、最终结论与使用边界

| 用途 | 是否可用 |
|---|---|
| 4bit 推理、单张截图理解、界面 OCR | 可用 |
| 命令级任务（bash / 文件整理 / 包管理 / 脚本） | 可用 |
| GUI 自主执行（看图定位小控件） | **不可用，已放弃** |
| 正式验收 / 需要精确 grounding | 走云端 BF16（能否解决未验证，属训练分布问题，不保证） |

风险与处置：

| 风险 | 处置 |
|---|---|
| 4bit 决策退化 | 不用于 GUI 自主执行，只做 bash 通道执行员 |
| bash 通道滥用 / 注入 | 一次性 VM 或隔离环境，宿主机凭据与浏览器 cookie 不挂载 |
| 显存被其它服务挤占 | 任务前检查端口占用，独占时再跑 |

---

## 六、参考来源

- [Mage-VL-Cowork 项目页](https://microsoft.github.io/Mage/cowork/)
- [Mage-VL-Cowork 技术报告 PDF](https://microsoft.github.io/Mage/cowork/assets/Mage-VL-Cowork.pdf)
- [microsoft/Mage GitHub（mage_vl_cowork/README）](https://github.com/microsoft/Mage/blob/main/mage_vl_cowork/README.md)
- [microsoft/Mage-VL-Cowork 模型卡](https://huggingface.co/microsoft/Mage-VL-Cowork)
- [本地运行拆解（DEV Community）](https://dev.to/alanwest/how-to-run-mage-vl-cowork-locally-microsofts-4b-agent-beats-sonnet-45-3dh4)
