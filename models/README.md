# models 模型库说明

> 本目录是本机所有大模型的统一存放根目录。三种运行方式：
> - **ComfyUI**：image / video / music(ACE-Step) 经 `extra_model_paths.yaml` 挂载给各 Loader 节点
> - **llama.cpp**：text\ / rag\ 下 GGUF 由 `llama.cpp\build\bin\Release\llama-server.exe` 直接加载（OpenAI 兼容服务，含 `/embeddings` 接口）
> - **Python .venv**：audio（VoxCPM2 / ASR / 对齐 / 声纹）/ music(MOSS-Music) / agent(Mage-VL-Cowork) 由 `d:\models\.venv` 下的脚本经 voxcpm / transformers / FunASR / qwen-asr / bitsandbytes 加载
>
> 硬件基线：RTX 5060 8GB 显存 + 32GB 内存。重写日期：2026-10-14。

---

# 第一部分：模型能力分析

## text\ —— LLM / VLM（llama.cpp，Q4_K_M 为主）

| 模型 | 大小 | 速度 | 擅长 | 功能定位 |
|---|---|---|---|---|
| `Qwen3.6-35B-A3B\` | 22.07 GB | ~34-39 tok/s；视觉 27s/张 | 五轮普适测试（中/英/推理/编程/工具调用）全能第一：推理 10/10、编程 5/5、工具调用 3/3 最干净、中英文写作与摘要双卷最高、视觉精细（BF16 mmproj）；MoE 激活 3B | 本地质量档主力（推理 / 编程 / agent / 视觉质检） |
| `Nanbeige4.2-3B\` | 2.57 GB | ~59 tok/s | 3B 性价比之王：中文写作 4.5、摘要 4.5、推理 9/10、编程 4/5、工具调用 3/3 全过；65,536 token 超长上下文 | 轻量全能（写作 / 推理 / 长文 / agent） |
| `LFM2.5-8B-A1B\` | 5.16 GB | ~200 tok/s | 激活仅 1B；工具调用 3/3 全过；输出卫生差（思维链泄进正文） | 速度优先的轻量 agent |
| `Qwen2.5-VL-7B\` | 5.54 GB | ~59-67 tok/s；视觉 4.8s/张 | 推理 9/10（5.7s/题）；视觉理解均衡 | 轻量视觉 + 快速推理 |
| `MiniCPM-V-4_6\` | 1.26 GB | ~200-275 tok/s；视觉 1.6-1.9s/张 | 超轻量（Q4 显存仅约 1.1 GB）；能力垫底（推理 6/10、编程 2/5），仅存速度价值 | 超轻视觉兜底（快速看图） |

> 已删除模型（五轮测试后确认）：**Ornith-1.0-9B**（编程 5/5 但偏科严重、输出卫生差）、**DeepSeek-R1-0528-Qwen3-8B**（思维链失控跨四轮复现截断）、**LFM2-24B-A2B**（被 Qwen3.6-35B 全面覆盖）、**Nemotron-3-Nano-Omni-30B-A3B**（2026-11-08 删除，推理 10/10 且最省 token、编程 5/5、唯一全模态，但中文卷偶发英文作答；测试结果与 bench 原始数据保留）。
> 未安装可选项（按 readme.txt 候选清单留档）：
> - **Nex-N2-Mini**：基于 Qwen3.5-35B-A3B 的后训练版，专注深度多步推理；自适应思考模式可省约 20% token 且不损失质量，适合复杂推理任务
> - **Qwen2.5-VL-7B-Instruct-Q3_K_M.gguf**：约 4.3 GB，比 Q4_K_M 更省显存，速度更快（约 1.9 秒/张），质量略降
> - **mmproj-Qwen2.5-VL-7B-Instruct-F16.gguf**：约 1.5 GB，视觉细节保留最好；对 8GB 显存偏大、易挤占 KV Cache（在库的 Q8_0 mmproj 约 1.0 GB 是均衡之选）

## rag\ —— 检索增强（llama.cpp，Q8_0）

| 模型 | 大小 | 擅长 | 功能定位 |
|---|---|---|---|
| `Qwen3-Embedding-0.6B\` | 0.6 GB | 文本向量化，中英文 embedding | RAG 检索：文档 / 查询 → 稠密向量 |
| `Qwen3-Reranker-0.6B\` | 0.75 GB | 检索结果重排序，提升 top-k 相关度 | RAG 重排：候选文档 → 相关性分数 |

> 两者均经 llama.cpp `llama-server.exe` 加载，走 OpenAI 兼容的 `/embeddings` 接口；Q8_0 量化在 8GB 显存下几乎无压力，可与 text LLM 服务错峰并存。

## agent\ —— 桌面操控 / GUI Agent（Python .venv，bitsandbytes NF4）

| 模型 | 大小 | 擅长 | 功能定位 |
|---|---|---|---|
| `mage-vl-cowork\` | ≈ 19 GB（NF4） | 基于 Qwen3-VL-32B 的 32B 桌面操控模型；截屏 → 推理 → 输出鼠标/键盘/命令动作；OSWorld Suite-2.0 54.9%；支持 `computer_use`（click/type/scroll/drag/keypress 等）+ `bash` 双通道 | **桌面 GUI 自动化**：自然语言指令操作任意桌面应用 |

> 状态：**模型权重待下载**（ModelScope / HuggingFace `MAGE-VL/Mage-VL-Cowork`），推理脚本已就绪于 `scripts\mage_cowork\`（`mage_config.py` 集中配置 + `mage_infer.py` 推理层）。
> 加载方式：transformers + bitsandbytes 4bit NF4，8GB 显存下 `max_context_tokens=12288`（BF16 KV 在 12K 约 1.8GB，32K 会挤爆显存）；推理参数固定 `temperature=0.7`、`top_p=0.8`、`max_new_tokens=4096`。
> 两种 Agent：
> - **Hybrid Agent**：`computer_use`（看图操作屏幕）+ `bash`（执行 shell 命令，经 WSL2 Ubuntu-24.04 桥接）双工具，适合需要文件/命令辅助的复杂任务
> - **GUI Agent**：仅 `computer_use`，纯屏幕操作
> 坐标体系：模型基准分辨率 1920×1080，坐标归一化到 [0,999]（官方明确用 999 而非 1000），截图 JPEG 质量 95；运行时按真实屏幕分辨率做坐标缩放。

## image\ —— 文生图（ComfyUI，按模型名分目录）

| 模型 | 大小 | 擅长 | 功能定位 |
|---|---|---|---|
| `Z-Image\` | ≈ 8.7 GB | 6B Turbo 8 步出图；艺术人像/摄影审美与皮肤质感明显更好；中文理解好；秒级快速迭代 | **文生图主力**（已实测） |
| `ERNIE-Image-Turbo\` | ≈ 13.1 GB | 复杂文字渲染、数据图表、UI 界面、海报排版能力突出；内置 Prompt Enhancer，多物体位置/遮挡等复杂指令翻车率低；材质光影更锐利 | 科研绘图 / 信息图 / 中文文字场景 |
| `Anima\` | ≈ 5.6 GB | 二次元向基底，2B 小模型常驻无压力（已实测，30 步 er_sde） | 动漫插画 |

> 每套目录下挂 `diffusion_models\`（主干）、`encoder\`（文本编码器）、`vae\`。
> 未安装可选项：
> - **Z-Image 标准版**（Q4 GGUF，约 5 GB）：与 Turbo 同底，支持 CFG，适合训练 LoRA、定制风格
> - **Krea2**（Q2 量化，约 4.6 GB）：风格参考、图生图见长
> - **FLUX.1-dev / FLUX.1-schnell**（NF4/GGUF，约 6-7 GB）：顶级画质，8GB 可运行但慢
> - ~~SenseNova-U1-8B-MoT-Infographic~~（Q3_K_M，约 3.5 GB）：高密度信息图/学术海报——技术路线已放弃并清理，勿再下载

## video\MiniMax-H3\ —— 文生视频主力（ComfyUI 原生节点链）

| 文件 | 大小 | 说明 |
|---|---|---|
| `diffusion_models\minimax_h3_fl2va_pruned_int8_convrot.safetensors` | 19.5 GB | **主干**。int8 + convrot 量化，932 个张量约 20.1B 参数；同分辨率比 Wan2.2-5B 快约 7.6 倍（244s/镜头 @ 832×480×73帧） |
| `encoder\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 15.0 GB | 提示词理解：NVFP4 + AWQ 4bit 的 Qwen3-VL-32B（H3 官方指定） |
| `vae\minimax_h3_video_vae_fp16.safetensors` | 5.0 GB | 视频 VAE，latent → 视频帧 |
| `vae\minimax_h3_audio_vae_fp32.safetensors` | 0.6 GB | 音频 VAE，与视频**同步生成原生音效轨**（相对 Wan2.2 的核心优势） |

能力要点：
- 本地可跑 768p 视频+音效联合生成（DiT，fl2va 变体即 H3-Base 的消费级量化版）
- 完整 H3 生成路径为三段：**H3-Context-IR**（多模态输入→结构化提示词，仅云端 API）→ **H3-Base**（本地，即本目录）→ **H3-Regenerate-2K**（超分，仅云端 API）。官方建议即使本地部署也先调 Context-IR 优化提示词
- 未安装可选件：`loras\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors`——4 步蒸馏 Turbo LoRA，768p 出片可再提速数倍（牺牲少量细节）

## music\ —— 音乐生成 + 音乐理解

| 模型 | 大小 | 擅长 | 功能定位 |
|---|---|---|---|
| `ACE-Step-1.5\` | ≈ 14.5 GB | 音乐扩散：文本/标签 → 48kHz BGM；safetensors 版 ComfyUI 0.37 核心原生支持，无需第三方节点包 | **BGM / 配乐生成**（产物示例：19s 蒸汽朋克配乐） |
| `MOSS-Music-8B\` | ≈ 16 GB | 音乐理解：自然语言描述情绪/风格/配器/情绪走向，识别调式/节拍/和弦进行，结构分析（主歌/副歌） | **音乐质检**：判定 ACE-Step 产出是否符合 prompt |

> ACE-Step 关键文件：`diffusion_models\acestep_v1.5_xl_base_bf16.safetensors`（9.5 GB 主干）+ `text_encoders\qwen_1.7b_ace15.safetensors`（3.5 GB，官方模板配 4b，本机以 1.7b 替代跑通）+ `qwen_0.6b`（1.1 GB 备用）+ `vae\ace_1.5_vae.safetensors`（0.3 GB）。
> 已放弃的 ACE-Step GGUF 轻量配置（无法接入 ComfyUI，产物已清理，留文件名备查）：
> - `acestep-v15-merge-sft-turbo-xl-ta-0.7-Q4_K_M.gguf`（≈2.85 GB，DiT 声学渲染器，SFT+Turbo 合并）
> - `acestep-5Hz-lm-4B-Q4_K_M.gguf`（≈2.1 GB，LM 作曲规划器，4B 最高规格）
> - `Qwen3-Embedding-0.6B-Q5_K_M.gguf`（≈0.45 GB，文本编码器，架构锁定）
> - `vae-BF16.gguf`（≈0.32 GB，音频解码，固定 BF16）
> MOSS-Music 版本说明：在库为 **Instruct 版**（直接提问式质检）；另有 **Thinking 版**（链式思维推理更强，适合复杂分析）未安装。
> MOSS-Music 加载：公开无 Q4 GGUF，改用 **bitsandbytes 4-bit NF4** 量化加载 bf16 权重（显存 ≈6 GB）；自带配置有多处兼容性缺陷需脚本内修复；generate 必须开采样（temperature=0.7、top_p=0.9、repetition_penalty=1.1），贪心会无限复读。质检以调性/配器/情绪/时长为主判据（BPM/拍号判断不准）。

## audio\ —— 语音识别 / 分离 / 对齐 / 合成

| 模型 | 大小 | 擅长 | 功能定位 |
|---|---|---|---|
| `Qwen3-ASR-0.6B\` | ≈ 1.3 GB | 中文场景识别质量好，无缝衔接 FunASR 工具包 | 对白转写主力（1.7B 版可按需切换，+2GB 显存） |
| `Qwen3-ForcedAligner-0.6B\` | 1.75 GB | 强制对齐：音文对齐出**字级时间戳**，11 语言，精度超 WhisperX 等传统方案（AAS 33ms） | 字幕时间轴 + 段内说话人细化（2026-10-14 起已启用，经 qwen-asr 包独立调用，绕开 FunASR 1.4.16 不透传参数的缺陷） |
| `campplus\` | ≈ 30 MB | CAM++ 声纹 embedding（192 维） | 说话人特征提取，配 KMeans/层次聚类做分离 |
| `fsmn-vad\` | 小 | FunASR 经典 VAD；对 1.5s+ 静音不敏感易并段 | 备选，对白场景优先 silero-vad（torch hub 在线加载，≥0.3s 静音即可切开） |
| `VoxCPM2\` | ≈ 4.7 GB | OpenBMB 出品，基于 MiniCPM-4 的 2B 参数 TTS；30 语种 + 9 种汉语方言；48kHz 录音室品质；**Voice Design**（纯文本描述生成全新音色，无需参考音频）；可控克隆（短音频 + 风格引导）；终极克隆（参考音频 + 对应转写，逐音还原）；内置 AudioVAE V2，16kHz 参考输入直接上采样到 48kHz 输出 | **语音合成主力引擎**：轻量一体化（无需外置 tokenizer）、多语种、可商用（Apache-2.0）；支持无参考音色的从零配音 |

> VoxCPM2 关键文件：`model.safetensors`（4.37 GB 主干）+ `audiovae.pth`（0.35 GB，AudioVAE V2 编解码）。调用方式：`pip install voxcpm` 后 `from voxcpm import VoxCPM` 加载，或经 `scripts/other/tts_run.py` 统一入口（自动分句 + badcase 重试）。
> 语音类候选方案留档（均未安装/已清理，当前链路不需要）：
> - **MOSS-TTS + MOSS-Audio-Tokenizer**（4.4 GB + 6.8 GB，共约 11.2 GB）——高保真音色克隆、长文本、时长/音标精细控制；需外置 tokenizer，24kHz 输出，不可商用；生成需参考音频、体积偏大、对人声情感的把握有所欠缺。2026-11 统一迁移至 VoxCPM2 后模型目录与调用脚本已清理，但作为备选方案并非完全不可用，部分场景表现良好；对比调研产物（`output/tts_compare/`、`output/tts_compare_styles/`）保留
> - **faster-whisper**（CTranslate2 优化引擎，配 `whisper-large-v3-turbo`，int8_float16 精度，显存约 3 GB）——速度比原版快数倍，整目录已删
> - **WhisperX**（faster-whisper 基座 + 词级时间戳 + 说话人分离，`large-v2`，beam_size=5，70 倍实时转录）——未安装；词级时间戳能力已由 Qwen3-ForcedAligner 覆盖且精度更高
> - **pyannote.audio 3.3.2**（峰值显存约 2.59 GB；注意 4.0.3 超 9.5 GB 不适合 8GB 显卡）——说话人分离业界标准，依赖问题已清理，由 campplus + KMeans 链路取代
> - **sherpa-onnx**（`pyannote-segmentation-3.0` INT8 仅 5.7 MB + 声纹提取约 2 MB，主打极致轻量 + Windows 原生）——实测 1.11.x 无 Windows wheel、1.12.40/1.13.8 高层 API 存在 pybind 绑定缺陷，不可用

---

# 第二部分：任务与模型配合链路

> 本部分按**任务类型**说明模型如何组合使用，与具体业务案例解耦。
> 各案例的具体实施方案（脚本 / 命令 / 产物）保存在对应案例目录，如 `铁锈海的女儿\README.md`。

## 任务一：文本生成（剧本 / 分镜 / 长文 / 代码）

按场景选型，全部经 llama.cpp `llama-server.exe` 以 OpenAI 兼容接口对外服务，`d:\models\scripts\run-*.bat` 一键拉起：

| 场景 | 选用模型 | 要点 |
|---|---|---|
| 快速对话 / 轻量任务 | LFM2.5-8B-A1B | 激活仅 1B，~200 tok/s 速度最快 |
| 长文档处理 | Nanbeige4.2-3B | 65,536 token 超长上下文，3B 性价比之王 |
| 高质量复杂推理 | Qwen3.6-35B-A3B | 推理 10/10 满分，`--cpu-moe` 调优后 ~34-39 tok/s |
| 本地 Agent | Qwen3.6-35B-A3B / LFM2.5-8B-A1B / Nanbeige4.2-3B | 工具调用 3/3 全过；Qwen 最干净，LFM 最快，Nanbeige 最轻 |
| 创意写作 | Qwen3.6-35B-A3B | 中英文写作与创造力双卷最高 |

组合方式：可同时拉起多路本地服务或与在线 API 混合，做多路由生成-对比-评测。

## 任务二：图像理解（图生文 / 看图问答）

| 场景 | 选用模型 | 要点 |
|---|---|---|
| 常驻轻量（多模型并存） | MiniCPM-V-4_6 | 显存仅 ≈1.1 GB，1.6-1.9s/张，~200-275 tok/s |
| 快速视觉 + 推理 | Qwen2.5-VL-7B | 4.8s/张，推理 9/10，~59-67 tok/s |
| 精细视觉质检 | Qwen3.6-35B-A3B | 视觉 5.0 分（27s/张），配 BF16 mmproj |

运行：llama-server 同时挂载主模型 GGUF + 同目录 mmproj 文件即可开放视觉能力。

## 任务三：文生图

| 场景 | 选用模型 |
|---|---|
| 通用快速出图 / 人像摄影 / 中文 prompt | Z-Image（8 步 Turbo） |
| 复杂文字渲染 / 信息图 / 海报 / 科研绘图 | ERNIE-Image-Turbo |
| 二次元插画 | Anima |

平台：ComfyUI，标准扩散节点链（`UNETLoader + CLIPLoader + KSampler + VAEDecode`；GGUF 主干用 `UnetLoaderGGUF`）。三套模型按目录独立存放，工作流按文件名解析，可共存挂载。

## 任务四：图生视频（含原生音效）

链路：MiniMax-H3 int8 主干 + Qwen3-VL-32B 编码器 + 视频/音频双 VAE，ComfyUI 节点链 `UNETLoader + CLIPLoader(minimax) + MiniMaxH3ImageToVideo + KSampler + 双VAEDecode`，一次前向同时产出视频帧与音效轨。

前后增强（仅云端 API，按需调用）：H3-Context-IR 优化提示词 → 本地 H3-Base 生成 → H3-Regenerate-2K 超分。
平台：ComfyUI，独占 ≈8 GB 显存。

## 任务五：音乐生成 → 质检闭环

```
ACE-Step-1.5（ComfyUI 生成 BGM）
    ──► 停 ComfyUI 释放显存 ──► MOSS-Music-8B（python .venv，4bit 质检）
```

- 生成：ComfyUI 节点链 `UNETLoader + DualCLIPLoader(type=ace) + TextEncodeAceStepAudio1.5 + EmptyAceStep1.5LatentAudio + VAEDecodeAudio`
- 质检：自然语言判定调性 / 配器 / 情绪 / 时长是否符合 prompt（BPM/拍号不作主判据）
- **互斥纪律**：两者不可同时驻留显存（≈8 GB vs ≈6 GB），切换前必须先停对方进程

## 任务六：语音合成（TTS / 音色克隆）

```
文本（+ 可选参考音色）
    ──► VoxCPM2（内置 AudioVAE V2，单模型完成 token 编码 → 解码）
    ──► 48kHz 波形
```

- **Voice Design**：无参考音色时，用括号包裹音色描述（如 `(温柔女声，语速偏慢)`）直接生成全新音色
- **音色克隆**：提供短参考音频做可控克隆，或参考音频 + 对应转写做终极克隆
- 多角色配音：对同一原始录音做变调派生多路参考音色，逐路合成
- 统一入口：`scripts/other/tts_run.py`（自动分句 + 交叉淡入拼接 + badcase 重试）
- 平台：python .venv（`pip install voxcpm`，≈5 GB 显存）

## 任务七：语音识别 + 说话人分离 + 字级字幕

```
音频 ──► silero-vad（切句，≥0.3s 静音即可切开）
           │
           ├─【文本线】────────────────────────────────────
           │  Qwen3-ASR-0.6B（逐段转写）
           │     │
           │     ▼  只依赖 ASR 文本，与声纹线并行
           │  [可选] Qwen3-ForcedAligner（字级时间戳）
           │     ├─► JSON 写 words 字段时间戳
           │     ├─► SRT 按句末标点/字数上限断行
           │     └─► 段内静音 ≥0.5s 再切子段 ─────────┐
           │                                         ▼
           ├─【声纹线】───────────────────── 子段重提 embedding
           │  campplus（段级声纹 embedding）           │
           │     │                                   ▼
           │     ▼                           归最近说话人中心 ◄── 汇流点：
           │  KMeans（人数已知）/ 层次聚类（自动）       需文本线子段 + 声纹线中心
           │     │                                   ▲
           │     └─────────► 说话人中心 ─────────────┘
           └─► 基线产出：段级「说话人 + 文本 + 起止时间」
```

平台：python .venv；ASR/VAD/声纹走 FunASR，字级对齐走 qwen-asr 包独立调用（绕开 FunASR 1.4.16 不透传 forced_aligner 参数的缺陷）。段内切分是 VAD 合并漏判时的兜底。

## 运行平台与显存分配速查

| 平台 | 承载模型 | 显存占用 | 互斥关系 |
|---|---|---|---|
| llama.cpp（llama-server） | text\ / rag\ 全部 GGUF | 1~8 GB 可调（`--n-cpu-moe` 卸载专家层到内存）；rag 两款合计 ≈1.4 GB 几乎无压力 | 与 ComfyUI 可错峰 |
| ComfyUI | image / video\H3 / music\ACE | ≈8 GB（满载独占） | **不可与 MOSS-Music 同时运行** |
| python .venv | audio 全套 / MOSS-Music / VoxCPM2 / agent\Mage-VL-Cowork | MOSS-Music ≈6 GB；ASR+Aligner+campplus 合计 ≈3 GB；VoxCPM2 ≈5 GB；Mage-VL-Cowork ≈8 GB（NF4 满载，独占） | MOSS-Music 与 ComfyUI 切换前必先停对方；Mage-VL-Cowork 需独占 8GB 显存，运行前须停 ComfyUI / MOSS-Music |

典型组合范式：**生成类任务串行排队**（文生图→图生视频→BGM 共用 ComfyUI，排队提交），**理解类任务错峰插入**（MOSS-Music 质检、ASR 转写在 ComfyUI 空闲或停止时运行），**文本服务常驻**（llama-server 显存占用小，可与上述错峰并存）。

---

## 已放弃的技术路线（明确留档，勿再投入）

| 路线 | 放弃原因 | 现替代方案 |
|---|---|---|
| **Wan2.2-TI2V-5B 视频生成** | 同分辨率比 MiniMax-H3 慢约 7.6 倍，且无原生音效轨，对比后落选 | video\MiniMax-H3 int8（全链路唯一视频主干） |
| **MiniMax-H3 w6a8 量化版** | 与 int8 速度仅差约 10%，int8 剪枝更少、质量更好 | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` |
| **SenseNova-U1 信息图路线** | 项目决策整体放弃该路线，模型、ComfyUI 工作流、节点包已全部清理 | 文字渲染/信息图需求由 ERNIE-Image-Turbo 承担 |
| **ACE-Step GGUF 轻量链路** | GGUF 版无法接入 ComfyUI（需脱离 ComfyUI 的专用引擎），与本库"音乐模型须可直接接入 ComfyUI"的约定冲突 | ACE-Step-1.5 safetensors 版（ComfyUI 0.37 核心原生支持） |
| **faster-whisper 转写链路** | 中文场景识别质量与生态衔接不如 Qwen3-ASR，链路统一到 FunASR 体系 | Qwen3-ASR-0.6B + FunASR |
| **pyannote 说话人分离** | 依赖与兼容问题难以解决（4.0.3 峰值显存超 9.5 GB 也不适合 8GB 显卡） | campplus 声纹 embedding + KMeans/层次聚类 |
| **sherpa-onnx 分离方案** | 1.11.x 无 Windows 可用 wheel；1.12.40/1.13.8 高层 API 存在 pybind 绑定缺陷，未暴露分段结果接口 | 同上（campplus 链路） |
| **MOSS-Music Q4 GGUF / HOT-Step CPP** | 公开无可用的 Q4 GGUF；仅存的 q8_0 GGUF 必须配专用 HOT-Step CPP 引擎，引入额外编译链 | bitsandbytes 4-bit NF4 动态量化加载 bf16 权重 |
| **FunASR 原生 distribute_spk** | FunASR 1.4.16 的 AutoModel 不向 Qwen3-ASR 透传 forced_aligner 参数，缺时间戳导致说话人分配失效 | 手动三段式流水线 + qwen-asr 包独立调用 ForcedAligner |
| **fsmn-vad 对白分段** | 对 1.5s 以上静音识别不敏感，易把多段独立语音合并成单个长段 | silero-vad（≥0.3s 静音即可切开） |
| **MOSS-TTS + MOSS-Audio-Tokenizer TTS 链路** | 需外置 tokenizer（6.8 GB）、24kHz 输出、不可商用；生成需参考音频、总体积偏大（11.2 GB）、对人声情感的把握有所欠缺；VoxCPM2 一体化更轻量、支持 Voice Design（无需参考音频）、48kHz、30 语种、Apache-2.0。MOSS-TTS 并非完全不可用，部分场景表现良好，保留为备选方案 | VoxCPM2（内置 AudioVAE V2，单模型完成编解码） |

已清理文件及大小（需要恢复时参考）：

| 文件 | 大小 |
|---|---|
| `video\Wan2.2-TI2V-5B\` 整目录（Q8_0 主干 + VAE） | 6.34 GB |
| `encoder\umt5-xxl\umt5-xxl-encoder-Q5_K_M.gguf`（Wan2.2 专属） | 3.86 GB |
| `video\MiniMax-H3\minimax_h3_fl2va_pruned_w6a8.safetensors` | 14.89 GB |
| `audio\MOSS-TTS\`（4.4 GB）+ `audio\MOSS-Audio-Tokenizer\`（6.8 GB） | ≈ 11.2 GB |
| `audio\faster-whisper\`（含 large-v3-turbo）、`audio\pyannote\` 及依赖 | ≈ 3 GB |
| SenseNova-U1、ACE-Step GGUF 相关下载/编译产物 | — |

恢复方式：视频模型按 `scripts\download_int8_pruned.py` 清单重下；音频模型从 ModelScope 仓库重下（稳定性优于 hf-mirror，无频繁断连限流）。

## 量化格式速查

| 格式 | 含义 | 本库文件 |
|---|---|---|
| Q4_K_M / Q5_K_M / Q6_K | llama.cpp 4/5/6bit K-量化 | text\ 全部 GGUF、Z-Image/ERNIE 主干 |
| nvfp4 + AWQ | 4bit 浮点 + AWQ 校准量化 | Qwen3-VL-32B 编码器 |
| int8 + convrot | 8bit 整数 + 卷积旋转融合 | H3 主干 |
| bitsandbytes 4bit NF4 | transformers 动态量化 | MOSS-Music-8B（加载时量化） |
| bf16 / fp16 / fp32 | 全精度浮点 | ACE 主干、双 VAE、MOSS 系、Anima |
