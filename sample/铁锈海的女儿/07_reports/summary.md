# 铁锈海的女儿 · 第一节本地视频生成工作流总结报告

> 项目路径: `D:\models\sample\铁锈海的女儿\`  
> 编写时间: 2026-10-08  
> 任务来源: 把《番外小说 铁锈海的女儿》第一节做成短片，研发一套**纯本地、画风可切换**的高质量视频生成工作流，并对比 Wan2.2 vs MiniMax H3 + 4 个本地 LLM 性能。**所有对比含时间成本维度。**

---

## 一、硬件与软件环境

| 项 | 规格 |
|---|---|
| GPU | RTX 5060 Laptop, **8 GB VRAM** |
| RAM | 32 GB |
| OS | Windows |
| ComfyUI | 端口 8188，启动参数 `--lowvram --cache-classic` |
| LLM 推理 | llama.cpp `llama-server.exe`（OpenAI 兼容 API） |
| 在线对照 | Trae GLM-5.2（在线） |
| 模型根目录 | `D:\models\models\video\` 经 `extra_model_paths.yaml` 映射（2026-10-12 由 models-gguf 改名） |

## 二、整体工作流

```
小说原文 (.docx)
    │
    ▼
[01] 节段提取 (Python)
    │   └─ 第一节 7 段 347 字 → section1.txt
    ▼
[02] 形象/场景设计 (人+LLM)
    │   └─ design.md：3 角色 × 2 年龄段 + 3 场景 + 风格定档
    ▼
[03] 分镜生成 (4 本地 LLM + 1 在线对照)
    │   ├─ Nanbeige4.2-3B   (88s, 质量 4.2)
    │   ├─ LFM2.5-8B-A1B    (12s, 质量 2.0) ❌中文理解失败
    │   ├─ DeepSeek-R1-8B   (18s, 质量 3.6)
    │   ├─ Qwen3.6-35B-A3B  (188s, 质量 5.0) 🥇
    │   ├─ Trae GLM-5.2     (28s, 质量 4.8) 🥈 在线基线
    │   └─ 综合定稿 → final_storyboard.json (6 镜头, 32s 总时长)
    ▼
[04] Wan2.2 视频生成 (ComfyUI 后台队列)
    │   ├─ shot1 1088x608x73, shot2-6 832x480x73
    │   ├─ steps=20, cfg=3.5, euler/simple, seed=42
    │   └─ 输出 ComfyUI/output/story_video/wan22_shot_XXX.mp4
    ▼
[05] MiniMax H3 T2VA 视频生成 (ComfyUI 后台队列)
    │   ├─ 6 镜头 832x480x73 (T2VA 同步音频)
    │   ├─ steps=24, cfg=1.0, euler/simple, seed=42
    │   └─ 输出 ComfyUI/output/story_video/minimax_h3_shot_XXX.mp4
    ▼
[06] 拼接与音频 (PyAV, 无 ffmpeg CLI)
    │   ├─ Wan2.2: 6 镜重编码统一 832x480 → 静音版 / + ACE-Step BGM + 对白
    │   ├─ MiniMax H3: 原生同步音效直拼 (+ 对白)，w6a8 与 int8 各一版
    │   └─ 对白: MOSS-TTS-Realtime 本地合成 3 句，按时间轴混入
    ▼
[07] 对比评测
    │   ├─ llm_bench.md       (LLM 性能/质量对比) ✅
    │   ├─ timebook_all.md    (视频生成时间账本) ✅
    │   └─ video_compare.md   (画质观感对比，待人工听评/看评)
    ▼
[08] 总结报告 (本文)
```

### 2.1 文件传输路径：跨目录数据流

本链路跨 **3 个根目录**，数据在三者之间流动：

| 根目录 | 作用 |
|---|---|
| `D:\models\sample\铁锈海的女儿\` | **项目根**：文本、分镜、成片、报告 |
| `D:\models\models\`（原 models-gguf，2026-10-12 改名） | **模型权重根**：video\、image\、audio\ 经 ComfyUI `extra_model_paths.yaml` 映射 |
| `D:\models\ComfyUI\output\` | **ComfyUI 产物根**：单镜头视频/BGM 先落此，拼接时拉回项目根 |

数据流主线：

```
docx → section1.txt → design.md → final_storyboard.json
     →（Wan / H3 双链 + 音频链并行产出单镜头和音频）
     → concat_mix.py 汇流 → 3 个最终成片 + 对比报告
```

### 2.2 每一步的输入 → 产物

| 步骤 | 脚本 | 输入 | 产物 |
|---|---|---|---|
| ① 节段提取 | [extract_section.py](file:///D:/models/sample\铁锈海的女儿/01_story_text/extract_section.py) | `D:\models\故事\番外小说 铁锈海的女儿.docx` | `01_story_text\section1.txt`（第一节 7 段） |
| ② 形象/场景设计 | 人工 + LLM | section1.txt | `02_design\design.md`（3 角色 × 2 年龄段、3 场景、画风定档） |
| ③ 分镜生成 | [llm_runner.py](file:///D:/models/sample\铁锈海的女儿/03_storyboard/llm_runner.py) | section1.txt + design.md 人工约束 | 中间：`llm_{5 家}.json` + `.time.json`；定稿：`03_storyboard\final_storyboard.json`（6 镜头，每镜头含 `wan_prompt` + `minimax_prompt`） |
| ④ 批量提交 | [batch_submit.py](file:///D:/models/sample\铁锈海的女儿/scripts/batch_submit.py) | final_storyboard.json + 分辨率/帧数参数 → POST ComfyUI `/prompt` | `04_wan22\_batch_submit_*.json`、`05_minimax_h3\_batch_submit_*.json`（含 prompt_id） |
| ⑤ ComfyUI 渲染 | ComfyUI 进程内 | 工作流 JSON + 模型权重（Wan2.2-5B GGUF / H3 w6a8·int8 + 文本编码器/VAE） | `ComfyUI\output\story_video\`：`wan22_shot_001~006.mp4`（**静音**）、`minimax_h3_shot_001~006.mp4`（**含原生音效**）、`minimax_int8_shot_001~006.mp4`（含音效），均 73 帧/镜 |
| ⑥ BGM 生成 | [submit_bgm.py](file:///D:/models/sample\铁锈海的女儿/scripts/submit_bgm.py) | ACE-Step-1.5 工作流（ComfyUI） | `ComfyUI\output\story_audio\bgm_steampunk_00001.flac`（19s） |
| ⑦ 对白合成 | [make_voice_refs.py](file:///D:/models/sample\铁锈海的女儿/scripts/make_voice_refs.py) + [gen_speech.py](file:///D:/models/sample\铁锈海的女儿/scripts/gen_speech.py) | 默认音色 wav → 变调派生参考音 → MOSS-TTS 音色克隆 | `06_compare\speech\ref_father.wav`、`ref_girl.wav`、`line1_father.wav`、`line2_girl.wav`、`line3_father.wav`（⑥⑦ 与 ④⑤ 并行） |
| ⑧ 拼接混音 | [concat_mix.py](file:///D:/models/sample\铁锈海的女儿/scripts/concat_mix.py) | 单镜头 mp4 + speech wav + BGM flac（三类素材汇流回项目根） | 见 2.3 成片表 |
| ⑨ 数据采集/报告 | [collect_timebook.py](file:///D:/models/sample\铁锈海的女儿/scripts/collect_timebook.py) | ComfyUI `/history` 接口 | `06_compare\timebook_all.md`、`07_reports\summary.md` |

### 2.3 步骤⑧拼接阶段的输入 → 最终成片

| 阶段 | 输入 | 产物 |
|---|---|---|
| concat | wan22 6 个单镜头（静音） | [final_wan22_silent.mp4](file:///D:/models/sample\铁锈海的女儿/04_wan22/final_wan22_silent.mp4) |
| bgm | final_wan22_silent + BGM flac + 对白 wav | [final_wan22_bgm.mp4](file:///D:/models/sample\铁锈海的女儿/04_wan22/final_wan22_bgm.mp4) |
| native | minimax_h3 6 镜头（原生音效）+ 对白 | [final_minimax_native.mp4](file:///D:/models/sample\铁锈海的女儿/05_minimax_h3/final_minimax_native.mp4) |
| native(int8) | minimax_int8 6 镜头（原生音效）+ 对白 | [final_minimax_int8_native.mp4](file:///D:/models/sample\铁锈海的女儿/05_minimax_h3/final_minimax_int8_native.mp4) |

所有成片规格统一：**832×480@24fps / 438 帧 / 18.25s**。

## 三、目录结构

```
铁锈海的女儿/
├── 01_story_text/        # 节段提取
│   ├── extract_section.py
│   └── section1.txt      # 第一节 372 字
├── 02_design/            # 形象/场景设计
│   └── design.md
├── 03_storyboard/        # 5 路 LLM 分镜
│   ├── llm_runner.py     # 统一调用脚本
│   ├── llm_nanbeige.{json,time.json}
│   ├── llm_lfm.{json,time.json}
│   ├── llm_deepseek.{json,time.json}
│   ├── llm_qwen35b.{json,time.json}
│   ├── llm_trae_glm5.{json,time.json}
│   └── final_storyboard.json   # 定稿 6 镜头
├── 04_wan22/             # Wan2.2 输出区
│   ├── final_wan22_silent.mp4  # 6 镜重编码统一 832x480，静音
│   ├── final_wan22_bgm.mp4     # + ACE-Step BGM + 对白
│   ├── _batch_submit_*.json    # 提交记录
│   └── _timebook.json          # 时间账本（脚本自动写）
├── 05_minimax_h3/        # MiniMax H3 输出区
│   ├── final_minimax_silent.mp4       # 拼接静音版
│   ├── final_minimax_native.mp4       # w6a8 原生音效直拼 + 对白
│   ├── final_minimax_int8_native.mp4  # int8 原生音效直拼 + 对白
│   ├── _batch_submit_*.json
│   └── _timebook.json
├── 06_compare/           # 对比报告
│   ├── llm_bench.md      # ✅ LLM 对比（已完成）
│   ├── timebook_all.md   # ✅ 视频时间账本（12+6 镜头全量数据）
│   ├── video_compare.md  # 视频画质对比（待人工看评后补）
│   ├── speech/           # MOSS-TTS 对白 wav（line1/2/3）
│   ├── download_int8.log # int8 模型下载日志
│   ├── wait_int8.log     # int8 批次监督日志
│   └── wait_progress.log # 首批 12 prompt 监督日志
├── 07_reports/           # 总结报告
│   └── summary.md        # 本文
└── scripts/              # 全套可复用脚本
    ├── start_llm_*.py/ps1/bat   # LLM 启动
    ├── llm_runner.py             # 分镜生成
    ├── submit_wan22.py           # Wan2.2 单镜提交
    ├── submit_minimax_h3.py      # MiniMax H3 单镜提交
    ├── batch_submit.py           # 批量非阻塞排队（支持 --unet_name/--prefix）
    ├── clear_queue.py            # 清空 ComfyUI 队列
    ├── concat_shots.py           # 早期 ffmpeg 拼接（已由 concat_mix.py 取代）
    ├── concat_mix.py             # PyAV 三阶段拼接+混音（concat/native/bgm）
    ├── gen_speech.py             # MOSS-TTS 对白合成
    ├── submit_bgm.py             # ACE-Step 1.5 BGM 工作流提交
    ├── collect_timebook.py       # 时间账本采集（/history timestamp 差值）
    ├── wait_all_done.py          # 后台监督全完成
    ├── wait_batch.py             # 多 prompt 轮询监督（写 wait_int8.log）
    └── download_int8_pruned.py   # 一键下载 8 个工作流模型文件（断点续传）
```

## 四、LLM 对比结论（已完成）

> 详见 [06_compare/llm_bench.md](file:///D:/models/sample\铁锈海的女儿/06_compare/llm_bench.md)

### 4.1 时间账本（含时间成本，秒）

| 模型 | 量化 | ngl | 端到端耗时(s) | prompt_tokens | completion_tokens | tokens/s | JSON 合规 |
|---|---|---|---|---|---|---|---|
| LFM2.5-8B-A1B | Q4_K_M | 99 | **11.62** | 831 | 2336 | 201.0 | ✓ |
| DeepSeek-R1-0528-Qwen3-8B | Q4_K_M | 99 | **18.46** | 718 | 1097 | 59.4 | ✓ |
| Trae GLM-5.2（在线） | N/A | N/A | ~28 | N/A | N/A | N/A | ✓ |
| Nanbeige4.2-3B | Q4_K_M | 99 | **88.07** | 735 | 4458 | 50.6 | ✓ |
| Qwen3.6-35B-A3B (no-think) | Q4_K_M | 24 | **188.04** | 724 | 1133 | 6.0 | ✓ |

### 4.2 质量排名

| 排名 | 模型 | 综合 | 关键评语 |
|---|---|---|---|
| 🥇 | Qwen3.6-35B-A3B | 5.0 | 6 镜头最完整，蒸汽朋克细节最浓 |
| 🥈 | Trae GLM-5.2（在线） | 4.8 | 8 镜头最全，含年龄分段人物卡 |
| 🥉 | Nanbeige4.2-3B | 4.2 | 蒸汽朋克细节浓，缺幼年玛莲 |
| 4 | DeepSeek-R1-8B | 3.6 | 4 镜头偏少，蒸汽朋克元素不足 |
| 5 | LFM2.5-8B-A1B | 2.0 | ❌ 把"铁锈海"误当人名 |

### 4.3 性价比（质量/耗时）

| 模型 | 性价比 | 适用场景 |
|---|---|---|
| DeepSeek-R1-8B | **0.195** | 快速草稿（推荐） |
| LFM2.5-8B-A1B | 0.172 | 速度优先但中文弱 |
| Trae GLM-5.2 | 0.171 | 在线对照基线 |
| Nanbeige4.2-3B | 0.048 | 质量优先（小模型） |
| Qwen3.6-35B-A3B | 0.027 | 最高质量但 188s 太慢 |

### 4.4 关键发现

1. **MoE 速度优势**：LFM2.5 A1B 实算 1B，速度 201 tok/s。
2. **推理模型在 8GB VRAM 极慢**：Qwen35B think 模式超时 10min；Nanbeige 推理 4458 token 耗 88s。
3. **CPU offload 是 35B 瓶颈**：Qwen35B ngl=24，prompt 处理 6 tok/s。
4. **小模型不一定快**：Nanbeige 3B 比 DeepSeek 8B 慢 4.8 倍。
5. **LFM2.5 中文弱**：MoE 小激活模型在中文细粒度理解上有缺陷。
6. **最终定稿策略**：综合 Qwen35B / DeepSeek / GLM-5.2 三家之长，6 镜头平衡叙事完整度与生成时长。

## 五、定稿分镜（6 镜头，32s 总时长）

| shot | 时长 | 描述 | 镜头运动 |
|---|---|---|---|
| shot_001 | 6s | 灰炉镇远景建立（蒸汽朋克工业城镇） | tilt_down |
| shot_002 | 5s | 幼年玛莲坐父亲肩头看蓝海 | push_in |
| shot_003 | 4s | 蓝色海面特写（铜壳机械蜻蜓） | pan_right |
| shot_004 | 5s | 父亲侧脸低语特写 | static |
| shot_005 | 6s | 时间流逝延时转场（蓝→锈红） | static |
| shot_006 | 6s | 成年玛莲独自站悬崖边 | pull_out |

分辨率: 1088x608（shot1） / 832x480（shot2-6） / 640x640（MiniMax 历史）；fps 24；帧数 73（≈3s）。

## 六、视频生成对比（✅ 数据已齐，画质观感待人工补评）

> **状态**: 18 个镜头（Wan2.2 6 + H3 w6a8 6 + H3 int8 6）全部跑完，时间账本由 `collect_timebook.py` 从 ComfyUI `/history` 采集完成。三个成片已产出，画质/音效观感待人工看评后写入 `video_compare.md`。

### 6.1 提交的 prompt_id 清单

| 模型 | 镜头 | prompt_id | 分辨率 |
|---|---|---|---|
| Wan2.2 | shot1 (重跑) | 6fc0d299-4638-46f0-ac40-6ff7dfc3c5a7 | 1088x608x73 |
| Wan2.2 | shot2 | 8b6460be-4c27-46b5-a343-397875257aa2 | 832x480x73 |
| Wan2.2 | shot3 | e89dcba8-236e-4831-96dc-f13ab5726533 | 832x480x73 |
| Wan2.2 | shot4 | 9211a69f-6c89-49b7-853a-12bd04743899 | 832x480x73 |
| Wan2.2 | shot5 | 33e5a4ab-20dc-4cbf-b479-bfc78f2e338a | 832x480x73 |
| Wan2.2 | shot6 | be402aa7-6618-4f46-aaa7-75daa2a67411 | 832x480x73 |
| MiniMax H3 | shot1 | 63a32b0f-d4ed-4d97-b130-83aa1d1f26ac | 832x480x73 |
| MiniMax H3 | shot2 | 67708b1a-983b-492f-a048-1a3c45ee0516 | 832x480x73 |
| MiniMax H3 | shot3 | c244d90f-3fad-4441-ac37-1b7d94141886 | 832x480x73 |
| MiniMax H3 | shot4 | 07f76911-b7f2-4eab-a891-161f37be18f4 | 832x480x73 |
| MiniMax H3 | shot5 | e1369254-3979-4372-ac09-ccb347660a7a | 832x480x73 |
| MiniMax H3 | shot6 | 8e3425d8-3be7-4d2e-a5d9-2574b150c2bb | 832x480x73 |

### 6.2 关键时间账本节点

> 数据已采集完成，详见 [06_compare/timebook_all.md](file:///D:/models/sample\铁锈海的女儿/06_compare/timebook_all.md)。汇总见 6.4 时间账本表与第七节。

### 6.3 历史跑通过的数据点（参考）

- **shot1 Wan2.2 第一次（1088x608x73）**: 加载 1:25 + 采样 20 步 × 92s = 30:50 + VAE tiled 解码（OOM 触发自动切换）→ SaveVideo 失败（绝对路径不允许），总执行约 35 min 浪费。
- **MiniMax H3 T2VA 测试（640x640x73）**: 加载 + 采样 24 步 × 7.6s = 3:01 + VAE，总 212s（4 min 左右），但当时 SaveVideo format 缺失也失败了。

### 6.4 音频与音乐对比维度（拼接阶段评测）

> 拼接（ffmpeg concat）之后进入成片听评。两个模型音频能力不对等，是重要对比点：

| 维度 | Wan2.2 TI2V-5B | MiniMax H3 (T2VA) |
|---|---|---|
| 原生音轨 | ❌ 无（纯画面静音） | ✅ 同步生成环境音效（海浪/风声等） |
| 音画同步 | N/A（无声可同步） | 模型原生对齐（生成时同步） |
| 镜头间音频连贯性 | N/A | ⚠️ 每镜头独立生成，切换处环境声会跳变（听评项） |
| 背景音乐 | ❌ 不生成 | ❌ 不生成（音效≠音乐） |

**补齐方案（已按原方案实施，2026-10-08）**：
1. 用本地 ACE-Step-1.5（ComfyUI 工作流）生成蒸汽朋克风格 BGM（`bgm_steampunk_00001.flac`，19s，steps=30/cfg=2.0）。
2. Wan2.2（无原生音轨）：静音画面 + 工作流生成的 BGM → `final_wan22_bgm.mp4`（PyAV mux，BGM 峰值归一 0.85，首尾 1s 淡化）。
3. MiniMax H3：直接使用与视频一起生成的原生同步音效，六镜头顺序直拼（音视频同步重编码，不做任何混音/响度处理）→ `final_minimax_native.mp4`。
4. ~~时间轴混音方案~~（每镜头音效按时间轴放置+BGM 铺底）**已弃用**：各镜头独立生成响度不一，叠加后音量忽大忽小，听感差。
5. 语音层（已加入，MOSS-TTS-Realtime 本地合成）：shot2 对话「好看吗？/好看。」(t=3.6/4.8s)、shot4 父亲低语「记住这个颜色，以后就见不到了。」(t=9.4s，3.52s 尾部自然延入 shot5 转场)；峰值归一 0.75，无参考音色（默认音色），配置在 `concat_mix.py SPEECH_CLIPS`。

**成片清单（最终产出，均为 832x480@24fps / 18.25s / 438 帧）**：
- `04_wan22/final_wan22_silent.mp4`（重编码统一 832x480，静音）
- `04_wan22/final_wan22_bgm.mp4`（画面 + ACE-Step 工作流 BGM + 对白）
- `05_minimax_h3/final_minimax_silent.mp4`（拼接静音版）
- `05_minimax_h3/final_minimax_native.mp4`（w6a8 原生同步音效直拼 + 对白）
- `05_minimax_h3/final_minimax_int8_native.mp4`（int8 原生音效直拼 + 对白）
- 工具：`scripts/concat_mix.py`（concat/native/bgm 三阶段，PyAV 实现，无 ffmpeg CLI）

**视频生成时间账本（ComfyUI /history 实测，832x480x73, seed=42）**：

| 模型 | 每镜头耗时 (s) | 平均 | 总计 |
|---|---|---|---|
| Wan2.2 TI2V-5B Q8_0 | 2246/1171/1344/2134/1815/1315 | **1671s ≈ 27.9min** | 167min |
| MiniMax H3 w6a8 | 222/219/221/224/221/216 | **221s ≈ 3.7min** | 22min |
| MiniMax H3 int8 convrot | 228/234/235/232/304/231 | **244s ≈ 4.1min** | 24min |

结论：同分辨率下 Wan2.2 比 MiniMax H3 慢 **7.6 倍**；int8 量化只比 w6a8 慢 ~10%（权重更大导致的 offload 开销），速度代价可忽略。

**听评打分项（video_compare.md 用）**：音效与画面内容匹配度 / 音量一致性 / 镜头切换处环境声连续性 / BGM 与叙事情绪匹配度 / 音画同步感。

**音频实现细节（实测数据）**：
- BGM：`bgm_steampunk_00001.flac`，19s，峰值归一 0.85，首尾各 1s 淡化。
- 对白（MOSS-TTS-Realtime，24kHz，音色克隆分角色）：`line1_father.wav` 0.80s（「好看吗？」F0≈122Hz 男声）、`line2_girl.wav` 1.04s（「好看。」F0≈160Hz 女童声）、`line3_father.wav` 3.44s（「记住这个颜色，以后就见不到了。」F0≈133Hz 男声）；峰值归一 0.75。参考音色由 `make_voice_refs.py` 从默认音色（F0 179Hz 偏女）变调派生：父亲 -5st（138Hz）、女儿 +1st（190Hz），再经音色克隆合成，男女声已区分（初版三句同音色无男女之分，已重做并重建全部成片）。
- 验证：`final_minimax_native.mp4` 音轨 RMS 0.118 / peak 0.8225，原生音效正常。曾有"没声音"疑惑，实为打开了 `_silent` 静音版文件——所有静音版均已加 `_silent` 后缀防混淆。

### 6.5 模型参数量与量化对比（safetensors header 实测）

| 模型 | 文件 | 参数量 | tensor 数 | 说明 |
|---|---|---|---|---|
| MiniMax H3 w6a8 | `minimax_h3_fl2va_pruned_w6a8.safetensors` (16 GB) | **15.90B** | 1151 | 主干，权重剪枝较多 |
| MiniMax H3 int8 convrot | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` (19.5 GB) | **20.11B** | 932 | 剪枝更少，参数量反超 w6a8 |
| Wan2.2 TI2V | Wan2.2-TI2V-5B | **5B** | — | 官方标称 5B |
| H3 文本编码器 | Qwen3-VL-32B (nvfp4, 15.7 GB) | ~32B | — | 另需加载，非 8GB 显卡常驻 |
| Wan 文本编码器 | UMT5-XXL | ~5.6B | — | — |

> 测算方法：解析 safetensors 文件头（前 8 字节长度 + JSON），对各 tensor 元素数求和。int8 版参数更多但单参数字节更少（剪枝少 + 8bit），所以文件反而比 w6a8 大；实际速度只慢 ~10%（见 6.4 时间账本）。

## 七、端到端时间账本总览

| 阶段 | 工具 | 端到端耗时 | 备注 |
|---|---|---|---|
| 1. 节段提取 | Python `extract_section.py` | <1s | 一次性 |
| 2. 形象/场景设计 | 人+LLM 协作 | ~5 min | 含 3 角色 × 2 年龄段 + 3 场景 + 风格定档 |
| 3a. LLM 调用（5 路） | llama.cpp / Trae | 11.62 + 18.46 + 28 + 88.07 + 188.04 ≈ **5.6 min**（并行则取 max 188s） | 见 LLM 对比表 |
| 3b. 分镜定稿 | 人综合 | ~3 min | 6 镜头定稿 |
| 4. Wan2.2 6 镜头 | ComfyUI | **167 min**（实测 2246+1171+1344+2134+1815+1315 = 10025s） | 含 shot1 首跑 35 min 浪费 |
| 5a. H3 w6a8 6 镜头 | ComfyUI | **22 min**（1333s） | 各 ≈ 3.7 min |
| 5b. H3 int8 6 镜头 | ComfyUI | **24 min**（1464s） | 各 ≈ 4.1 min |
| 6. 拼接+音频 | PyAV `concat_mix.py` | ~1 min/版 | 三版本共 ~3 min |
| 6.5 BGM 生成 | ACE-Step-1.5 本地（ComfyUI 节点） | ~4 min | 蒸汽朋克 19s，steps=30 |
| 6.6 对白合成 | MOSS-TTS-Realtime 本地 | ~1 min | 3 句，CUDA 下每句几秒 |
| 7. 报告编写 | 人+脚本 | — | 本文档 |
| **总计（单模型成片）** | Wan2.2 全流程 ≈ **3.2h**；H3 全流程 ≈ **0.7h** | | 不含下载/报告 |

## 八、关键决策与教训

1. **SaveVideo 节点不能用绝对路径**：ComfyUI 限制 SaveVideo 只能写到 `output/` 子目录内，filename_prefix 必须是相对路径如 `story_video/{prefix}`。曾导致 shot1 Wan 第一次跑 35 min 后失败。
2. **ComfyUI error 不缓存节点输出**：失败重跑会从 0 开始，所有节点（包括 16GB 模型加载）重跑。
3. **1088x608 VAE 解码会 OOM**：8GB VRAM 下 1088x608x73 帧的 VAE tiled 解码自动触发（慢但能成）。
4. **MiniMax H3 length 网格**：必须落在 17k+5 网格（5,22,39,56,73,90,107,124...），73 帧 ≈ 3s @ 24fps。
5. **Qwen3.6-35B 在 8GB VRAM 下需要禁 think 模式**：否则 think token 生成超 10min 超时。
6. **LFM2.5 中文理解弱**：MoE A1B 实算量小，但中文细粒度理解不足，把"铁锈海"误当人名。
7. **系统无 ffmpeg CLI 时用 PyAV**：`.venv` 内 PyAV 18.1 可完成视频重编码、音频混音、AAC 编码、mux 全链路。
8. **PyAV mp4 mux 铁律**：容器所有流（视频+音频）必须在写入第一个 packet 之前 `add_stream` 完成，否则原生崩溃（0xC0000414）；AAC 流必须设 `ast.time_base = Fraction(1, SR)`。
9. **各镜头独立生成的音效响度不一致**：叠加混音后音量忽大忽小。最终音频方案回归"模型能力对等"原则：Wan2.2 用工作流生成 BGM（ACE-Step），MiniMax H3 直接用与视频同步生成的原生音效，对白（MOSS-TTS）作为独立第三层按时间轴混入。
10. **MOSS-TTS 本地调用**：需 `sys.path.insert(0, 模型目录)` 才能导入 `mossttsrealtime`；`reference_audio_path=None` 合法（默认音色）；新版 torchaudio.save 依赖 torchcodec，绕过方案是标准库 `wave` + numpy 写 int16 wav。
11. **ComfyUI `/history` 时间字段**：`status.messages` 中为 `timestamp`（无 execution_time / start_time 字段），取 execution_start 与 execution_success 两条的差值即为总耗时。
12. **int8 vs w6a8 实测结论**：int8 版参数量更大（20.1B vs 15.9B）但速度只慢 ~10%，画质对比见成片；w6a8 剪枝更多、文件更小（16GB vs 19.5GB）。

## 九、工作流推荐

### 9.1 纯本地高质量分镜推荐

- **首选（质量优先）**: Qwen3.6-35B-A3B (no-think)，188s 出 6 镜头，质量 5.0
- **备选（速度优先）**: DeepSeek-R1-0528-Qwen3-8B，18s 出 4 镜头，质量 3.6
- **在线对照**: Trae GLM-5.2，28s 出 8 镜头，质量 4.8

### 9.2 视频生成模型推荐

**实测对比表（832x480x73, seed=42, 8GB VRAM, --lowvram）**：

| 维度 | Wan2.2 TI2V-5B | MiniMax H3 w6a8 | MiniMax H3 int8 |
|---|---|---|---|
| 参数量 | 5B | 15.90B | 20.11B |
| 权重文件 | ~9 GB (Q8_0) | 16 GB | 19.5 GB |
| 每镜头耗时 | **1671s ≈ 27.9 min** | **221s ≈ 3.7 min** | **244s ≈ 4.1 min** |
| 采样步数 | 20 (cfg 3.5) | 24 (cfg 1.0) | 24 (cfg 1.0) |
| 原生音轨 | ❌ 无 | ✅ 同步环境音效 | ✅ 同步环境音效 |
| 配乐方案 | ACE-Step 工作流生成 BGM | 原生音效直拼（无配乐） | 原生音效直拼（无配乐） |
| 画质/一致性/提示词遵循 | 待人工看评 | 待人工看评 | 待人工看评 |

**结论（速度与工程维度）**：
1. **速度**：同分辨率下 Wan2.2 比 H3 慢 **7.6 倍**——5B 反而比 15.9B 慢，主因是 Wan 采样计算量大 + Q8_0 offload 开销，H3 量化方案对 8GB 显卡更友好。
2. **int8 代价可忽略**：比 w6a8 只慢 ~10%，若画质更好则值得用。
3. **音频能力**：H3 T2VA 原生同步音效是独家优势（音画同步、免后期）；Wan2.2 需 ACE-Step BGM 补齐。
4. **推荐**：8GB VRAM 本地短片生产首选 **MiniMax H3（w6a8 起步，追求画质上 int8）**；Wan2.2 适合对画面风格有特殊要求且不计时间的场景。

### 9.3 复用指南

1. 改画风：编辑 `02_design/design.md` 的 `style` 字段（如改成 `anime` / `cyberpunk` / `watercolor`），重跑 03 分镜。
2. 改故事：替换 `01_story_text/section1.txt`，重跑 02-07。
3. 改分辨率：调 `scripts/batch_submit.py --res WxH`。
4. 改帧数：调 `--length N`（MiniMax 须落在 17k+5 网格）。
5. 改 LLM：编辑 `scripts/start_llm_*.py` 启动其他模型，跑 `llm_runner.py --model <name>`。
6. 补模型文件：`python scripts/download_int8_pruned.py` 一键下载 8 个工作流模型（断点续传、跳过已完整文件）。

---

## 附录 A：磁盘清理记录（2026-10-08）

**背景**：综合对比后确认 MiniMax H3 性价比最高（同分辨率比 Wan2.2 快 7.6 倍、原生同步音效、8GB 显存友好），进而在 H3 两版中只保留 int8 链路（w6a8 与 int8 速度仅差 ~10%，int8 剪枝更少、参数更全）。因磁盘空间，本地视频生成路径最终仅保留 **MiniMax H3 int8** 一条；音频/人声路径与全部报告、脚本保留。

**已删除（两轮合计释放 ≈ 25.11 GB）**：

| 轮次 | 类别 | 路径 | 大小 |
|---|---|---|---|
| 第 1 轮 | Wan 模型权重 | `models-gguf\video\Wan2.2-TI2V-5B\`（Q8_0 主干 + VAE，整目录） | 6.34 GB |
| 第 1 轮 | Wan 文本编码器 | `models-gguf\encoder\umt5-xxl\umt5-xxl-encoder-Q5_K_M.gguf` | 3.86 GB |
| 第 1 轮 | Wan 单镜头中间产物 | `ComfyUI\output\story_video\wan22_shot_001~006.mp4`（6 个） | 17.2 MB |
| 第 2 轮 | H3 w6a8 主干 | `models-gguf\video\MiniMax-H3\minimax_h3_fl2va_pruned_w6a8.safetensors` | 14.89 GB |
| 第 2 轮 | H3 w6a8 单镜头 | `ComfyUI\output\story_video\minimax_h3_shot_001~006.mp4`（6 个） | ≈ 20 MB |

**已保留**：
- **视频生产链路（唯一）**：MiniMax H3 int8 —— 模型 `MiniMax-H3\diffusion_models\minimax_h3_fl2va_pruned_int8_convrot.safetensors`（19.53GB）、共享文本编码器 `MiniMax-H3\encoder\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`、共享 VAE（`MiniMax-H3\vae\` 视频 fp16 + 音频 fp32）、6 个 int8 单镜头、成片 `05_minimax_h3\final_minimax_int8_native.mp4`。
- **画质对比成片（档案，体积小）**：`04_wan22\final_wan22_bgm.mp4` + `final_wan22_silent.mp4`（Wan 证据）；`05_minimax_h3\final_minimax_native.mp4` + `final_minimax_silent.mp4`（w6a8 证据）。各目录提交记录/timebook 保留。
- 音频链路：ACE-Step-1.5（模型+BGM flac）、MOSS-TTS-Realtime + MOSS-Audio-Tokenizer、`06_compare\speech\` 全部参考音与对白。
- 全部脚本与全部报告（含历史路径引用，作为档案保留，不代表文件仍在盘）。
- LLM 分镜模型（文本路径，未处理）。

> 如需恢复被删链路：模型可由 `scripts/download_int8_pruned.py` 清单重新下载；报告第六节/2.2 表保留完整提交参数与 prompt_id 记录。

---

**报告状态**: 数据采集全部完成（LLM 5 路、视频 18 镜头、三版成片、模型参数量）。已定稿：LLM 对比（第四节）、时间账本（6.4/第七节）、音频最终方案（6.4 节，时间轴混音方案已弃用）、模型参数量（6.5 节）、模型推荐（9.2 节）、磁盘清理记录（附录 A）。**唯一待补项**：三版成片的画质/音效人工看评结论 → 写入 `06_compare/video_compare.md` 后回填 9.2 表末行。
