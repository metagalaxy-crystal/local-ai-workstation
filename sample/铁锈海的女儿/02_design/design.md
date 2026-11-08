# 铁锈海的女儿 · 第一节 → 视频生成工作流设计

> 编写于 2026-10-08。基于本地资源摸底和用户决策对齐。

## 1. 目标

把《番外小说 铁锈海的女儿》第一节（7 段 347 字）做成一段 5-15 秒的短片，
研发一套**可复用、画风可切换、纯本地**的高质量视频生成工作流，并做对比评测。

## 2. 资源摸底

### 2.1 硬件
- GPU: RTX 5060 Laptop, 8 GB VRAM
- RAM: 32 GB
- ComfyUI 已编译并运行（端口 8188），含 comfy-kitchen + comfy-aimdo 动态显存

### 2.2 视频生成模型
| 模型 | 类型 | 大小 | 加载方式 | 状态 |
|------|------|------|----------|------|
| Wan2.2-TI2V-5B | T2V/I2V 文生视频 | Q8_0 ~5.3GB GGUF | UnetLoaderGGUF | 已下载 |
| MiniMax-H3 | FL2VA 文生视频+音频 | w6a8 15.24GB safetensors | 原生 UNETLoader | 已跑通 |

### 2.3 本地 LLM（5 个，做性能对比）
| 模型 | 量化 | 大小 | 备注 |
|------|------|------|------|
| Nanbeige4.2-3B | Q4_K_M | 2.40 GB | 最快，基线 |
| LFM2.5-8B-A1B | Q4_K_M | 4.80 GB | MoE，A1B 实际算量小 |
| DeepSeek-R1-0528-Qwen3-8B | Q4_K_M | 4.68 GB | 推理模型，适合分析 |
| Ornith-1.0-9B | Q4_K_M | 5.38 GB | heretic-MTP |
| Qwen3.6-35B-A3B | Q4_K_M | 19.71 GB (+0.84GB mmproj) | MoE A3B，最强 |

调用方式：llama.cpp 的 `llama-server.exe`（已编译）启动 OpenAI 兼容 API。

### 2.4 在线对比
- 使用 Trae 内置对话模型（GLM-5.2）作为"在线大模型"对照组。

## 3. 整体工作流

```
小说原文
    │
    ▼
[模块 A] 文本理解（5 个 LLM 各跑一遍，对比）
    │  → 输出：人物卡（外貌、年龄、性格）
    │  → 输出：场景卡（地点、光线、氛围）
    │  → 输出：分镜脚本（每镜头提示词 + 时长 + 镜头运动）
    ▼
[模块 B] 形象设计 / 参考图生成
    │  → 人物参考图（FLUX 或 SDXL）
    │  → 场景参考图（同上）
    ▼
[模块 C] 视频生成（Wan2.2 vs MiniMax H3，对照同分镜）
    │  → 1088x608 横屏，每镜头 5-8 秒
    ▼
[模块 D] 后期拼接 / 配乐 / 字幕
    ▼
[模块 E] 评测对比 + 总结报告
```

## 4. 关键决策

| 项 | 选择 | 理由 |
|----|------|------|
| 画风（首轮） | 蒸汽朋克写实 | 贴合小说原味（铁锈、机械、工业污染） |
| 视频尺寸 | 1088x608 | 短剧横向主流；8GB 显存可承载 Wan2.2 |
| 帧数 | 73-97 帧 ≈ 3-4s | 显存约束 |
| 本地 LLM 对比组 | Nanbeige 3B / LFM2.5 8B / DeepSeek-R1 8B / Qwen3.6 35B | 用户全选 |
| 在线对比组 | Trae 内置（GLM-5.2） | 用户指定 |
| 文本处理实现 | llama-server OpenAI 兼容 API + Python 客户端 | 标准接口便于切换 |

## 5. 子任务与产物路径

```
D:\models\sample\铁锈海的女儿\
├── 01_story_text\
│   ├── extract_section.py        # docx → txt
│   └── section1.txt              # 第一节正文
├── 02_design\
│   └── design.md                 # 本文档
├── 03_storyboard\
│   ├── llm_nanbeige3b.json       # 各 LLM 输出
│   ├── llm_lfm2_8b.json
│   ├── llm_deepseek_r1_8b.json
│   ├── llm_qwen35b.json
│   ├── llm_trae_glm5.json       # 在线对比组
│   ├── final_storyboard.json     # 综合后定稿分镜
│   └── llm_runner.py             # 通用调用脚本
├── 04_wan22\
│   ├── shot_001.mp4
│   ├── shot_002.mp4
│   └── final.mp4                 # 拼接成品
├── 05_minimax_h3\
│   ├── shot_001.mp4 (含音轨)
│   └── final.mp4
├── 06_compare\
│   ├── llm_bench.md              # 4 LLM + 1 在线 性能/质量对比
│   └── video_compare.md          # Wan vs MiniMax 对比
└── 07_reports\
    └── summary.md                # 总报告
```

## 6. 执行计划（按顺序）

1. **跑通基础 T2VA**：MiniMax H3 640x640x73 已成功（`minimax_h3_t2va_00001_.mp4`）。
2. **启动本地 LLM 服务**：先跑 Nanbeige 3B（最小，验证调用链）。
3. **写 LLM 调用脚本**：统一 prompt → 输出 JSON 分镜。
4. **跑 5 个 LLM 出分镜**：包括我（GLM-5.2）直接产出。
5. **综合分镜定稿**：人为挑选/综合成 `final_storyboard.json`。
6. **生成人物参考图**：用 ComfyUI 的人物写实工作流。
7. **Wan2.2 跑 1088x608**：每镜头 73-97 帧。
8. **MiniMax H3 跑同分镜**：1088x608x73（验证尺寸是否支持）。
9. **拼接成品**：ffmpeg concat。
10. **写对比报告**。

## 7. 对比维度

每个对比项都记录**时间成本**（端到端耗时）：

### 7.1 LLM 文本处理对比矩阵
| 模型 | 加载耗时 | 首响应 token | 端到端耗时 | 输出质量(1-5) | JSON 合规性 | 备注 |
|------|----------|--------------|------------|----------------|--------------|------|
| Nanbeige4.2-3B | | | | | | |
| LFM2.5-8B-A1B | | | | | | |
| DeepSeek-R1-0528-Qwen3-8B | | | | | | 推理链可能拖长耗时 |
| Qwen3.6-35B-A3B | | | | | | |
| Trae 内置(GLM-5.2) 在线 | N/A | | | | | 对照组 |

### 7.2 视频生成对比矩阵
| 维度 | Wan2.2 TI2V-5B | MiniMax H3 w6a8 |
|------|----------------|-----------------|
| 模型加载耗时 | | |
| 单镜头采样耗时(1088x608x73) | | |
| VAE 解码耗时 | | |
| 总端到端耗时 | | |
| 显存峰值 | | |
| 是否带音轨 | 否 | 是 |
| 视觉质量(1-5) | | |
| 一致性(1-5) | | |
| 提示词遵循度(1-5) | | |

### 7.3 端到端流程时间账本
| 阶段 | 模型 | 耗时 | 累计 |
|------|------|------|------|
| 文本理解 | Nanbeige 3B | | |
| 文本理解 | LFM2.5 8B | | |
| 文本理解 | DeepSeek-R1 8B | | |
| 文本理解 | Qwen3.6 35B | | |
| 文本理解 | Trae GLM-5.2 | | |
| 参考图生成 | FLUX/SDXL | | |
| Wan2.2 单镜头×N | Wan2.2 | | |
| MiniMax 单镜头×N | MiniMax H3 | | |
| 拼接后期 | ffmpeg | | |
| **总耗时** | | | |

## 8. 风险与回退

- Wan2.2 在 8GB 显存跑 1088x608 可能 OOM → 回退到 832x480 或 608x608
- MiniMax H3 1088x608 未验证 → 先小尺寸测，再升
- Qwen3.6-35B 19.7GB 全部加载到 8GB VRAM → 走 CPU/GPU 混合 offload
- LLM 输出 JSON 格式不稳 → 加 retry + schema 校验

## 9. 文生图/图生文链路实测（2026-10-11，08_image_pipeline）

硬件：RTX 5060 Laptop 8GB / 32GB RAM；ComfyUI `--lowvram --cache-classic`，端口 8188；
图生文走 llama-server（OpenAI 兼容 API，端口 8081），脚本与产物在 `08_image_pipeline/`。

### 9.1 模型清单（均字节级校验完整）
| 文件 | 量化 | 大小 | 位置 |
|------|------|------|------|
| Z-Image-Turbo（unsloth） | Q4_K_M GGUF | 4.67 GiB | models/image/Z-Image/ |
| Qwen3-4B 文本编码器（worstplayer） | Q6_K GGUF | 3.08 GiB | models/image/Z-Image/encoder/ |
| Flux VAE ae.safetensors（Comfy-Org） | fp32 | 0.32 GiB | models/image/Z-Image/vae/ |
| MiniCPM-V 4.6（ggml-org） | Q4_K_M | 0.49 GB | models/text/MiniCPM-V-4_6/ |
| MiniCPM-V mmproj | Q8_0 | 0.68 GB | 同上 |
| Qwen2.5-VL-7B-Instruct（ggml-org） | Q4_K_M | 4.36 GB | models/text/Qwen2.5-VL-7B/ |
| Qwen2.5-VL mmproj | Q8_0 | 0.79 GB | 同上 |

### 9.2 实测结果
| 测试项 | 结果 |
|--------|------|
| 文生图 1088×608，8 步 cfg=1（冷启动含加载） | 30.6s，显存峰值 6384 MB |
| 同参数第二次（模型已缓存） | 19.3s，显存峰值 6711 MB |
| MiniCPM-V 4.6 图生文（冷启动） | 7.85s / 136 tok / 17.33 tok/s |
| MiniCPM-V（热，端到端联动） | 2.17s / 187.21 tok/s |
| Qwen2.5-VL-7B 图生文（全量上卡） | 2.23s / 388 tok / 174.31 tok/s，显存 7096 MB |
| Z-Image + MiniCPM 同时常驻 | 5531 / 8151 MB（余量约 2.6GB，方案 A 成立） |
| Z-Image + Qwen2.5-VL 同时常驻 | 不成立；需先 POST /free 卸载图像模型再切换（方案 B，约 5 秒切换） |

两个 VLM 均准确识别蒸汽朋克分镜内容（人物、锈船、齿轮、黄昏工业城市）；
Qwen2.5-VL 回答更详尽（388 vs 187 token）、构图建议更具体，MiniCPM-V 胜在轻量可常驻。

### 9.3 使用方式
- 文生图：`python 08_image_pipeline/test_t2i.py [--prompt "..." --seed N]`
- 图生文：`vlm_server.ps1 -Action start -Vlm minicpm|qwenvl [-Ngl 999]` → `python test_i2t.py --image X --question "..."`
- 端到端：`python run_e2e.py --vlm minicpm`（自动生图→起 VLM→分析→停服务）
- 方案 B 切换：先 `curl -X POST http://127.0.0.1:8188/free -d '{"unload_models":true,"free_memory":true}'` 再起 qwenvl

### 9.4 追加模型实测（Anima / ERNIE-Image-Turbo）

#### 模型清单
| 文件 | 量化 | 大小 | 位置 |
|------|------|------|------|
| Anima-Base-v1.0（circlestone-labs/Anima） | safetensors | 3.89 GiB | models/image/Anima/diffusion_models/ |
| Qwen3-0.6B TE（随 Anima） | safetensors | 1.11 GiB | models/image/Anima/encoder/ |
| qwen_image_vae（随 Anima） | safetensors | 0.24 GiB | models/image/Anima/vae/ |
| ERNIE-Image-Turbo（unsloth） | Q4_K_M GGUF | 4.67 GiB | models/image/ERNIE-Image-Turbo/ |
| Ministral-3-3B TE（baidu/ERNIE-Image-Turbo） | safetensors | 7.17 GiB | models/image/ERNIE-Image-Turbo/encoder/ |
| flux2-vae（Comfy-Org） | safetensors | 0.31 GiB | models/image/ERNIE-Image-Turbo/vae/ |

#### 实测结果
| 测试项 | 结果 |
|--------|------|
| Anima-Base 832×1216，30 步 cfg=4.5 er_sde/normal | 41.4s，显存峰值 6092 MB |
| ERNIE-Image-Turbo 1024×1024，8 步 cfg=1 euler/simple | 39.5s，显存峰值 6689 MB |

#### 备注
- Anima：二次元风格出图质量高，TE 自动识别为 Qwen3-0.6B（CLIPLoader type=stable_diffusion 即可），VAE 用 qwen_image_vae
- ERNIE：TE 为 Ministral-3-3B，主模型 Q4 量化，--lowvram 模式下 TE 卸载到内存可跑。中文大字标题渲染完全正确，三栏信息图布局清晰；小字仍有乱序（8 步 Turbo 正常水平）
- ERNIE 排障记录：两次失败根因均为 TE 文件损坏（跨源断点续传拼接）。注意 Comfy-Org 官方 repack 的 ministral-3-3b.safetensors（7,717,637,511 B）本身含 `vision_tower.*` 与 `tekken_model`，这是 VLM 完整结构的正常特征，**不能**据此判损坏；正确判据是 safetensors header 自洽性：`8 + header_len + max(data_offsets[1]) == file_size`
- ~~SenseNova-U1~~：已放弃（2026-10-12）。接入过程中连环排障（GGUF arch 标错、采样器 text conditioning 结构特殊），接入成本过高，模型/工作流/节点包已全部清理，释放约 23.3 GB

## 10. 音频管线方案（音乐生成 + 音乐理解 + 人声识别，2026-10-12 设计）

三条独立子链路，共用 `models\music\` / `models\audio\` 目录；8GB VRAM 下全部**独占运行**（同一时刻只跑一条），切换沿用 `unload_models + free_memory` 习惯。

### 10.1 ACE-Step GGUF 版音乐生成（已放弃，留档）

> **最终决策（2026-10-12，用户）**：放弃 GGUF 轻量链路——四组件 GGUF 仅支持 acestep.cpp 引擎，无法接入 ComfyUI，而本项目音乐生成需统一在 ComfyUI 编排。**保留现有 safetensors 版（`music\ACE-Step-1.5\`，14.5 GB）作为唯一音乐生成链路**（已验证出曲）。相关下载与编译已中止，产物待清理。以下调研内容留档：

用户指定四组件（总计 ≈5.7 GB，比现有 bf16 safetensors 版 14.4 GB 省 8.7 GB）：

| 组件 | 文件 | 大小 | 作用 |
|---|---|---|---|
| DiT（声学渲染器） | `acestep-v15-merge-sft-turbo-xl-ta-0.7-Q4_K_M.gguf` | ≈2.85 GB | SFT+Turbo 合并版，决定音质上限 |
| LM（作曲规划器） | `acestep-5Hz-lm-4B-Q4_K_M.gguf` | ≈2.1 GB | 歌词理解与作曲规划，4B 为最高规格 |
| Text Encoder | `Qwen3-Embedding-0.6B-Q5_K_M.gguf` | ≈0.45 GB | 架构锁定，不可替换 |
| VAE | `vae-BF16.gguf` | ≈0.32 GB | 音频解码，固定 BF16 |

与现有 safetensors 版的关键差异：**新增 LM 作曲规划环节**（歌词/标签 → 结构化作曲计划 → DiT 按计划渲染），是 v1.5 GGUF 工作流的完整形态；主干 bf16→Q4_K_M 后显存占用从 9.5 GB 降到 2.85 GB。

- 存放：`models\music\ACE-Step-GGUF\`（按项目规则 GGUF 直接放模型名目录下）
- 接入方式（已确认）：GGUF 四组件**不能接入 ComfyUI**——scragnog/CC-TM 仓库均为 acestep.cpp（C++17 GGML 引擎）专用格式，ComfyUI-GGUF 插件仅支持图像扩散 arch，ComfyUI 原生 ACE-Step 1.5 节点链无 LM 规划环节。正确路径：编译 acestep.cpp（`D:\models\acestep.cpp`，cmake+MSVC+CUDA 13.2，`-DGGML_CUDA=ON`）→ `ace-server` HTTP API 编排（贴合项目脚本模式）
- 双轨并行：ComfyUI 音乐链路继续用现有 safetensors 版（已验证出曲）；GGUF 版经 acestep.cpp 跑通并对比音质/显存/速度后再决定是否替换
- 清理约定：GGUF 版对比通过后，旧 `music\ACE-Step-1.5\`（safetensors 版 14.4 GB）列入清理清单，确认后删除

**safetensors 版 ComfyUI 链路实测（✅ 2026-10-13）**：

- 无需任何第三方节点包：ComfyUI 0.37 核心原生支持（`UNETLoader` + `DualCLIPLoader(type="ace")` + `TextEncodeAceStepAudio1.5` + `EmptyAceStep1.5LatentAudio` + `KSampler` + `VAEDecodeAudio` + `SaveAudio`）
- 工作流：`scripts\workflow_acestep_bgm_api.json`（API 格式，可改 tags/bpm/duration/keyscale 复用；模型名用反斜杠且不带 `music/` 前缀，如 `ACE-Step-1.5\vae\ace_1.5_vae.safetensors`）
- 实测：C 小调 72BPM 4/4 拍纯音乐 30s，LM 音频码生成 ≈3s + 30 步扩散 ≈20s + VAE 解码，总耗时 ≈41s；产物 `ComfyUI\output\acestep_bgm_00001.flac`；bf16 全量 ≈14 GB 靠 DynamicVRAM 动态调度在 8GB 卡跑通

### 10.2 MOSS-Music-8B 音乐理解（生成质检闭环，✅ 2026-10-13 验证通过）

MOSI.AI / OpenMOSS / 上海创智学院开源的音乐理解模型：用自然语言描述音乐的情绪、风格、配器、情绪走向，识别调式/节拍/和弦进行，做结构分析（主歌/副歌）。本项目用它做 **BGM 质检闭环**：

```
分镜情绪需求 → ACE-Step 生成 BGM → MOSS-Music 分析产出物 → 与需求比对 → 不合格则调提示词重生成
```

**落地情况（2026-10-13）**：

- 版本：Instruct 版 bf16（16.86 GB，4 分片）。**Q4 GGUF 不存在**——公开仓库仅 q8_0/f16 且为 HOT-Step CPP 专用格式（9.6 GB 超 8GB 显存），改用 **bitsandbytes 4-bit NF4 量化加载** bf16 原版（显存 ≈6 GB，等效 Q4）
- 存放：`models\music\MOSS-Music-8B\`
- 调用：transformers + bitsandbytes（llama.cpp 音频模态不可行，已验证放弃该路径），独立脚本 `scripts\analyze_music.py`
- 脚本内置四处兼容性修复（模型自带 config/processor 有缺陷）：
  1. `auto_map` 未注册 AutoModel → importlib 虚拟包手动加载 `MossMusicModel`
  2. `audio_config` 保持 dict 但模型期望对象 → AttrDict monkey-patch
  3. processor 不返回 `audio_input_mask` → 按 `audio_token_id` 手动构建
  4. mel 默认 bfloat16 与编码器 fp16 卷积层冲突 → `audio_data` 统一转 float16；generate 开启采样（temp=0.7, top_p=0.9, rep_penalty=1.1）修复贪心解码无限复读
- **首次质检实测**（对 `acestep_bgm_00001.flac`）：调性 C 小调、钢琴配器、内省忧郁情绪、30s 时长全部判定与生成参数一致；BPM/拍号识别有偏差（模型弱项，不影响质检结论）。闭环全链路打通

### 10.3 人声识别（ASR + 说话人分离）

动机：MOSS-TTS 生成的对白需要**自动校验**（台词是否读对、生成字幕时间轴），混音成片后需要可检索的转写文本。

| 组件 | 选择 | 显存 | 定位 |
|---|---|---|---|
| ASR 首选 | faster-whisper `large-v3-turbo`，int8_float16 | ≈3 GB | 转写 + 时间戳，8GB 显存黄金选择 |
| ASR 进阶 | WhisperX `large-v2`（beam_size=5） | 8GB 可跑 | 词级时间戳（剪辑/口型对齐），二期可选 |
| ASR 备选 | Qwen3-ASR 0.6B / 1.7B | 8 / 10 GB | 中文场景更好，需要时再评 |
| 说话人分离 | pyannote.audio **3.3.2**（锁版本） | 峰值 ≈2.59 GB | 多角色混音质检；**4.0.3 超 9.5 GB 禁装** |
| 分离轻量版 | pyannote GGUF（≈5.7 MB） | 极低 | 仅做快速检测时考虑 |

说明：本片对白是两个角色**分开生成**的，说话人已知，分离非刚需——pyannote 列为可选组件，主要用于外部素材或最终混音成片的抽检。

- 形态：pip 包（CTranslate2），不走 ComfyUI；模型缓存放 `models\audio\faster-whisper\` / `models\audio\pyannote\`
- 脚本：`scripts\transcribe_voice.py`（转写 + SRT 字幕导出 + 与台本逐句比对）

> **【2026-10-12 路线变更】上表整体作废**：faster-whisper + WhisperX + pyannote 路线已弃用并删除（模型权重与 17 个 pip 依赖全部卸载）。变更原因：
> 1. pyannote 3.3.2 本地三件套无法加载——`Model.from_pretrained` 只接受 .bin 路径或 HF id，传入 config.yaml 会被 torch.load 当旧式 pickle，报 `could not find MARK`（pyannote/model.py:590）；
> 2. ctranslate2 基于 CUDA 12 编译，与本地 torch cu130 冲突需手动注入 DLL，链路脆弱；
> 3. 升级 pyannote 4.x 需连带 lightning 全家桶重构，风险不成比例。
>
> **新路线（已二次变更，见下）**：~~sherpa-onnx（纯 CPU，内存占用 <1 GB，无 torch/ffmpeg 依赖）~~
>
> **【2026-10-12 二次变更】sherpa-onnx 路线亦放弃并清理**（模型目录 `models\audio\sherpa-diarization\`、`models\audio\sensevoice\` 与 pip 包 sherpa-onnx / sherpa-onnx-core 已全部删除，脚本 diarize_transcribe.py 标注作废留档）。原因：sherpa-onnx 高层 diarization API 存在 pybind 绑定缺陷——1.12.40 与 1.13.8 的 `OfflineSpeakerDiarizationResult` 均未暴露分段访问接口（不可下标、不可迭代），1.11.x 又无 Windows wheel，段数据无法取出。
>
> **最终路线：Qwen3-ASR + FunASR（手动三段式流水线）**
>
> | 组件 | 选择 | 定位 |
> |---|---|---|
> | VAD 分段 | silero-vad（FunASR 内置） | 对白短静音切分，比 fsmn-vad 敏感 |
> | ASR | Qwen3-ASR 0.6B（bf16，显存 ≈4 GB） | 逐段转写，带标点 |
> | 说话人分离 | campplus（FunASR `model="cam++"`）提 embedding + sklearn KMeans 聚类 | 每段一个说话人单元，无需句子级时间戳 |
>
> **关键实现**：FunASR 1.4.16 的 AutoModel 不向 Qwen3ASR 传递 `forced_aligner`（源码注释提到但未实现），导致 `spk_model` 内部的 `distribute_spk` 因缺时间戳失败。最终绕过方案——手动三段式：silero-vad 切段 → 逐段 Qwen3-ASR 转写 + campplus 提 embedding → KMeans(preset_spk_num) 聚类分配说话人。每个 VAD 段视为一个说话人单元，无需 ForcedAligner。
>
> - 脚本：
>   - `scripts\diarize_transcribe_funasr.py`：转写 + 说话人分离 + SRT/JSON 导出（实测：父-女-父三句全对，说话人分配正确）
>   - `scripts\transcribe_voice.py`：纯转写 + SRT 字幕导出 + 与台本逐句比对
> - 模型：Qwen3-ASR-0.6B、campplus、fsmn-vad 从 ModelScope 下载，**按模型名扁平存放** `models\audio\Qwen3-ASR-0.6B\` / `models\audio\campplus\` / `models\audio\fsmn-vad\`（脚本以 FunASR 注册表 key + `model_path=本地路径` 加载，不依赖任何 hub 缓存目录；`hf-home` 缓存已删除。Qwen3-ForcedAligner-0.6B 同目录保留备用）

### 10.4 显存预算与调度

| 链路 | VRAM 估算 | 运行方式 |
|---|---|---|
| ACE-Step 1.5 safetensors 出曲 | bf16 ≈14 GB 权重，DynamicVRAM 动态调度，8GB 卡可跑 | ComfyUI 独占（实测 2026-10-13） |
| MOSS-Music-8B NF4 4-bit 分析 | ≈6 GB（等效 Q4） | 独立进程独占（实测 2026-10-13，需先停 ComfyUI） |
| Qwen3-ASR 0.6B 转写 | bf16 ≈4 GB | 独立进程独占 |
| MOSS-TTS 语音合成（现有） | 已实测 | ComfyUI 独占 |

任何时刻只跑一条链路；与图像/视频链路互斥（同样独占）。ComfyUI 与独立脚本进程切换时需先停对方释放显存。

### 10.5 实施顺序

1. ✅ 等 ministral TE 下载完成（当前 34%）→ ERNIE 出图测试（9.4 节）
2. ~~下载 ACE-Step GGUF 四组件→ acestep.cpp 出曲测试~~：已放弃（见 10.1 最终决策），音乐生成保留 safetensors 版 ComfyUI 链路
3. ✅ MOSS-Music-8B：~~下载 Q4~~（Q4 GGUF 不存在，改 bf16 + bitsandbytes NF4）→ 音频理解调用方式已验证（transformers 路线，4 处兼容修复）→ 对 `acestep_bgm_00001.flac` 完成首次质检（调性/配器/情绪/时长全部一致，见 10.2）
4. ~~faster-whisper 转写脚本~~ → ~~sherpa-onnx diarize_transcribe.py~~ → ✅ Qwen3-ASR + FunASR 手动三段式（diarize_transcribe_funasr.py / transcribe_voice.py）：实测转写全对、说话人分离正确；模型改扁平目录本地加载
5. ✅ 全部实测结果已补记本节（2026-10-13）

### 10.6 风险与回退

- ~~LM GGUF 节点不认~~：已确认 GGUF 四组件走 acestep.cpp（见 10.1 接入方式），无 ComfyUI 节点问题；编译失败时回退 safetensors 版（已验证可出曲）
- ~~MOSS-Music 音频模态不支持 llama.cpp~~：已验证放弃 llama.cpp，落地 transformers + bitsandbytes NF4 路线（见 10.2）
- ~~Q4 音质损失可感知~~：Q4 GGUF 不存在，NF4 4-bit 直接作用于 bf16 原版权重，无二次量化损失；实测分析质量满足质检需求
- **BPM/拍号识别偏差**：MOSS-Music 对速度/拍号判断不准（72BPM 4/4 判成 168BPM 2/4），质检时以调性/配器/情绪/时长为主判据，BPM 仅作参考
- **bitsandbytes 依赖**：Windows 上 0.50.2 实测可用；若未来升级破坏 NF4 加载，analyze_music.py 的修复逻辑需同步核对
