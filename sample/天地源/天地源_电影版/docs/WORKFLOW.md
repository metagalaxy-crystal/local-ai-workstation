# 天地源 · 电影版（v3）—— 工作流、参数与复现手册

> 本片是把 `d:\models\sample\天地源\片段-天地源.docx`（第一人称散文）做成的约 80 秒电影感短片。
> v3 相对 v2（`天地源_进阶版`）的升级目标：**全流程 100% 本地、按电影镜头规格重做**。
>
> 1. **画面**：Z-Image-Turbo 重绘 11 张 2.33:1 关键帧 → MiniMax-H3 高分辨率图生视频（1120×480）→
>    光流慢放 + 2.39:1 遮幅 + 胶片洗印感（halation / 拉丝眩光 / 色散 / 颗粒 / 片门晃动）
> 2. **旁白**：MOSS-TTS-Realtime 本地声纹克隆（参考音为 v2 的 Yunxi 试音样本），分句合成 + 磁带变速 + 话筒链
> 3. **配乐**：ACE-Step 1.5 本地生成两段配乐（主线 76s + 高潮 40s），按镜头强度弧线铺底
> 4. **环境音**：11 条 numpy 合成 stem，按镜头推子、关键动作对位（沿用 v2 思路）
> 5. **母带**：两遍 loudnorm 到 -16 LUFS / TP -1.5
>
> 所有产物、脚本、参数、提示词都在本目录内，可按第 7 节顺序逐步重跑。

---

## 1. 目录结构

```
d:\models\sample\天地源\天地源_电影版\
├─ images\            11 张关键帧 shot01..11.png（1344×576，Z-Image-Turbo）+ 同名 .json
├─ clips\             11 段动态片段 s01..s11.mp4（1120×480，MiniMax-H3 i2v）+ 同名 .json
├─ audio\
│  ├─ lines\          逐句旁白 line01..11.wav（MOSS-TTS 本地克隆，48 kHz）
│  ├─ stems\          11 条环境音 stem：wind/leaves/city/steps/glass/crystal/
│  │                  fire/paper/insects/drips/bell
│  ├─ mix.wav         混音总线（未做母带）
│  └─ master.wav      母带（-16 LUFS / TP -1.5）
├─ music\             bgm_main.flac（76s）+ bgm_climax.flac（40s）+ music_report.json（ACE-Step）
├─ build\
│  ├─ tts_report.json   每句旁白的分句文本、时长
│  ├─ timeline.json     镜头时长、起点、旁白入点、慢放倍率
│  ├─ video_noaudio.mp4 合成画面（1080p24，CRF20，2.39:1 遮幅）
│  └─ verify.py         成片自检（镜头窗口响度、stem 对位、旁白存在性）
├─ out\               成片：天地源_电影版_短片.mp4
├─ scripts\           全部可执行脚本（见第 5 节）
└─ docs\              本手册
```

---

## 2. 技术路线

```
散文文本 ─► Z-Image-Turbo 关键帧(11) ─► MiniMax-H3 图生视频 ─► clips\s01..s11.mp4
              (1344×576)                  (1120×480,24fps,3~5s)         │
散文文本 ─► MOSS-TTS 本地克隆分句 ─► line01..11.wav ─┐                  │
                                                    ▼                  ▼
                                        timeline.json ──► render.py（光流慢放/2.39:1遮幅/
ACE-Step 1.5 ─► bgm_main + bgm_climax ──┐                胶片感/字幕/叠化）
                                        │                              │
env_audio.py（11 条 stem，按镜头推子）──┴─► mix.py（闪避/标定）─► mix.wav
                                                                    │
                                        finish.py（loudnorm 2-pass + 封装）─► out\*.mp4
```

---

## 3. 环境（已在本机验证）

| 项 | 值 |
|---|---|
| GPU | RTX 5060 Laptop，8 GB 显存 |
| RAM | 32 GB |
| ComfyUI | `D:\models\ComfyUI`，服务 `http://127.0.0.1:8188`（--lowvram） |
| Python | **`D:\models\.venv\Scripts\python.exe`**（系统 python 不可用） |
| 关键帧模型 | Z-Image-Turbo（ComfyUI 本地工作流，1344×576） |
| 视频模型 | MiniMax-H3 i2v：`minimax_h3_fl2v_int8` + `qwen3vl_32b_nvfp4` + `minimax_h3_video_vae_fp16` |
| i2v 工作流 | `D:\models\scripts\comfyui\minimax-h3\workflow_i2v.json` |
| 配乐模型 | ACE-Step 1.5（ComfyUI 本地，输出 flac） |
| TTS | MOSS-TTS-Realtime（本地 PyTorch，bf16，cuda）+ MOSS-Audio-Tokenizer |
| 参考音 | `d:\models\sample\天地源\天地源_进阶版\tts_test\zh-CN-YunxiNeural.wav`（仅作声纹参考） |
| 合成 | numpy / scipy / opencv / Pillow |
| ffmpeg | `C:\Program Files\EVCapture\ffmpeg.exe`（旧版，无 xfade，转场全部 Python 逐帧合成） |

### 3.1 踩过的坑（重要）

1. **Z-Image 工作流节点字段名是 `prompt` 不是 `text`**。`gen_images.py` 曾按惯例写 `text`，
   结果 ComfyUI 静默使用工作流默认提示词，shot01 曾生成为一张蒸汽朋克少女图。
   现已在 `gen_images.py` 修正并全量重生成。**改工作流后务必抽查首帧**。
2. **MOSS-TTS 与 transformers 4.57 的兼容垫片全部在 `tts_moss.py` 内**
   （4.57 改名 + `create_causal_mask` + 用 soundfile 替代 torchaudio）。
   不要去改共享的模型文件。
3. 配置文件名必须是 `v3_config.py`，**不能叫 `config.py`**——会与 `D:\models\scripts\config.py` 冲突。
4. comfy_client 的 `fetch_outputs` / `upload_image` 要传 `Path` 对象；PowerShell 串联命令用 `;` 不用 `&&`。
5. i2v 首帧一致性已抽查验证（S01/S02/S07/S09 首帧与关键帧构图一致），管线可信。

---

## 4. 分镜与时间轴（当前成片）

| # | 镜头 | 画面 | 镜长(s) | 起点 | 旁白入点 | 慢放 |
|---|---|---|---|---|---|---|
| 1 | S01 | 街角骑楼夜景，湿路面 | 9.11 | 0.00 | 1.55 | 2.43× |
| 2 | S02 | 枯藤小道通向圆亭 | 6.72 | 8.39 | 9.34 | 1.79× |
| 3 | S03 | 亭内柱廊 | 5.03 | 14.39 | 15.19 | 1.65× |
| 4 | S04 | 低位石子阵纹 | 7.95 | 18.70 | 19.60 | 2.12× |
| 5 | S05 | 玻璃穹顶 | 7.39 | 25.93 | 26.78 | 2.43× |
| 6 | S06 | 穹顶特写（虚无） | 6.54 | 32.60 | 33.50 | 2.15× |
| 7 | S07 | 三界光柱 | 11.98 | 38.42 | 39.42 | 2.32× |
| 8 | S08 | 雨后林荫道（人间） | 7.81 | 49.68 | 50.63 | 2.08× |
| 9 | S09 | 地狱走廊背影 | 7.45 | 56.77 | 57.77 | 1.99× |
| 10 | S10 | 天堂/碎纸空间 | 8.94 | 63.50 | 64.55 | 2.38× |
| 11 | S11 | 夜幕空亭拉远 | 8.70 | 71.72 | 72.92 | 1.68× |

总长 **80.42 s**（含叠化尾部），24 fps，1920×1080，有效画面 2.39:1（1920×804），镜头间 0.72 s 叠化。

---

## 5. 脚本清单（`scripts\`）

| 文件 | 作用 | 是否可单独重跑 |
|---|---|---|
| `v3_config.py` | 所有路径、镜头表、台词、LEAD/TAIL 节奏 | — |
| `jobs_img.json` | 11 张关键帧的 Z-Image 提示词与种子（seed 101–111） | — |
| `jobs.json` | 11 个镜头的 i2v 提示词、帧数、种子（seed 501–511） | — |
| `01_start_comfyui.ps1` | 启动本地 ComfyUI 并等待就绪 | 是 |
| `gen_images.py` | Z-Image-Turbo 生关键帧（`--only shot07` / `--force`） | 是 |
| `gen_clips.py` | MiniMax-H3 图生视频（`--job S07 --force` / `--all`），写 sidecar json | 是 |
| `tts_moss.py` | MOSS-TTS 本地克隆分句合成 + 磁带变速 + 话筒链（`--only 7`） | 是 |
| `gen_music.py` | ACE-Step 本地配乐（bgm_main / bgm_climax，`--force`） | 是 |
| `timeline.py` | 用旁白实际时长推导时间轴，填慢放倍率 | 是（依赖 tts + clips） |
| `env_audio.py` | 合成 11 条环境音 stem | 是（依赖 timeline） |
| `render.py` | 画面合成（光流慢放/遮幅/胶片感/字幕/叠化）；`TEST=1` 只渲首镜 | 是 |
| `mix.py` | 旁白 + ACE-Step 配乐 + stem 混音，自动标定、闪避 | 是 |
| `finish.py` | 两遍 loudnorm + 封装 | 是 |
| `run_all.ps1` | 一键按顺序跑完 | — |
| `tts_probe.py` | MOSS-TTS 探针/试音 | 是 |
| `..\build\verify.py` | 成片自检 | 是 |

---

## 6. 设计细节（为什么这么做）

### 6.1 关键帧：Z-Image-Turbo 重绘

* v2 沿用 v1 旧图，v3 全部用 Z-Image-Turbo 按电影构图重绘：**1344×576（2.33:1）**，seed 101–111，
  单张约 20–25 s。提示词强调画幅感、布光与场景细节，产物带同名 `.json` 留档。

### 6.2 动态：MiniMax-H3 高分辨率 i2v + 光流慢放

* 分辨率从 v2 的 832×480 提到 **1120×480**（32 的倍数），steps 从 16 提到 **20**。
* H3 帧数仍受网格约束：`length = 17k + 5`（73/90/124 帧 = 3.04/3.75/5.17 s）。
* 镜头需要 5–12 s，v2 用线性混帧，v3 改用 **Farneback 双向光流重定时**
  （`render.py` 的 `optflow_retime`）：对每对相邻帧算前向/后向光流，按目标时刻 warp + 混合，
  慢放 1.65–2.43× 后运动仍然连续，不跳帧、无重影。
* 提示词统一要求：保持构图/结构不变、写实物理运动（雾、光晕、微尘、火星、纸片、倒影）、
  摄影机按 `v3_config.py` 的 `cam` 描述运动、不加文字、不加人物（S09 保留原背影）。

### 6.3 旁白：MOSS-TTS 本地声纹克隆

* 不再用 edge-tts（需联网、音色固定）。MOSS-TTS-Realtime 本地加载（bf16 + sdpa），
  以 v2 的 Yunxi 试音样本作**声纹参考**，按标点分句逐句生成，再解码拼接。
* 采样率 24 k → 48 k 线性重采样；**磁带变速**按情绪档（`MOOD_RATE`）微调语速；
  长停顿按 1/3 概率插入极轻换气；**话筒链**（高通/存在感提升/齿音衰减/压缩/短混响）；
  每小句 RMS 归一到 0.105，整句再归一到 0.112，句间不再忽大忽小。
* 11 句总语音 **56.9 s**。全部本地完成，不联网。

### 6.4 配乐：ACE-Step 1.5 本地生成

* `bgm_main.flac`（76 s，全片主线）+ `bgm_climax.flac`（40 s，高潮层）。
* `mix.py` 按镜头强度弧线（三界 0.92 / 地狱 0.95 / 结尾 0.36）给主线做包络；
  高潮层从 S07 入点铺入，2.4 s 高斯边缘，峰值 0.38。
* 若 `music\` 下文件缺失，`mix.py` 自动回退到程序化配乐（v2 的 numpy 方案）。

### 6.5 画面统一：电影化渲染链

`render.py` 每帧依次处理（全部 numpy/OpenCV/PIL）：

1. **光流重定时** → 上采到 1920 宽、中心裁到 1920×804（2.39:1）
2. **胶片洗印感**：曝光 1.04 → 分离色调（暗部偏青、高光偏暖）→ 降饱和 0.88 →
   filmic S 曲线 LUT（抬黑位、压白位）
3. **Halation**：高光红橙光晕（高斯 σ9）
4. **变形宽银幕拉丝眩光**：极亮点横向拉丝（σX42 / σY1.2，青蓝色）
5. **边缘径向色散**：R 外扩、B 内收 1.2 px
6. **胶片颗粒**：10 张预生成噪声轮换；**暗角**；**片门微晃**（慢随机游走 ±0.6 px）
7. **遮幅**：上下黑边成 1080p；**字幕**（STSONG 40px）画在下黑边，随旁白入点淡入淡出
8. **转场**：0.72 s 叠化；S06/S07/S10 叠加过黑（DIP 0.18–0.36）

输出 `build\video_noaudio.mp4`（libx264 CRF20 / preset slow）。全片约 1933 帧。

### 6.6 环境与混音

沿用 v2 方案：11 条 stem 按镜头 `place` 生成增益曲线（边界交叉 + 高斯平滑），
单发事件（脚步/水滴/玻璃/虫鸣/纸/火星/钟）按绝对时间排布。
混音时各 stem 按 95 分位场内 RMS 自动标定；旁白出现时音乐 -55%、环境音 -22%。

### 6.7 响度

`mix.wav` → 两遍 `loudnorm`（先测再打）到 **I=-16 LUFS / TP=-1.5 dBTP / LRA=11**，aac 192k 封装。

---

## 7. 复现步骤

在 `d:\models\sample\天地源\天地源_电影版` 下打开 PowerShell。
（除 TTS 外所有生成步骤都依赖 ComfyUI 服务。）

### 7.1 启动 ComfyUI

```powershell
.\scripts\01_start_comfyui.ps1
```

### 7.2 关键帧（Z-Image-Turbo）

```powershell
& "D:\models\.venv\Scripts\python.exe" .\scripts\gen_images.py           # 缺哪张补哪张
& "D:\models\.venv\Scripts\python.exe" .\scripts\gen_images.py --only shot07 --force
```

### 7.3 动态片段（MiniMax-H3）

```powershell
& "D:\models\.venv\Scripts\python.exe" .\scripts\gen_clips.py --all
& "D:\models\.venv\Scripts\python.exe" .\scripts\gen_clips.py --job S07 --force
```

帧数必须是 17k+5；分辨率必须是 32 的倍数。

### 7.4 旁白（MOSS-TTS 本地，不需要 ComfyUI）

```powershell
& "D:\models\.venv\Scripts\python.exe" .\scripts\tts_moss.py           # 全部 11 句
& "D:\models\.venv\Scripts\python.exe" .\scripts\tts_moss.py --only 7  # 单句
```

### 7.5 配乐（ACE-Step）

```powershell
& "D:\models\.venv\Scripts\python.exe" .\scripts\gen_music.py          # 缺则生成
```

### 7.6 时间轴 → 环境音 → 画面 → 混音 → 母带

```powershell
$py = "D:\models\.venv\Scripts\python.exe"
& $py .\scripts\timeline.py
& $py .\scripts\env_audio.py
& $py .\scripts\render.py      # $env:TEST="1" 可只渲首镜自检
& $py .\scripts\mix.py
& $py .\scripts\finish.py
& $py .\build\verify.py        # 自检
```

### 7.7 一键

```powershell
.\scripts\run_all.ps1                          # 已有产物会跳过
.\scripts\run_all.ps1 -ForceVideo              # 重生成全部片段
.\scripts\run_all.ps1 -SkipGenerate            # 只重做旁白/音效/画面/成片
```

---

## 8. 参数速查

| 想改什么 | 改哪里 |
|---|---|
| 台词 / 镜头表 / 摄影机运动 | `v3_config.py`: `TXT`, `SHOTS`（`cam` 写进 i2v 提示词） |
| 旁白情绪 / 语速 | `v3_config.py`: `LINE_MOOD`；`tts_moss.py`: `MOOD_RATE` |
| 句子前后留白 | `v3_config.py`: `LEAD`, `TAIL` |
| 叠化时长 | `v3_config.py`: `XFADE` |
| 关键帧提示词 | `scripts\jobs_img.json` |
| i2v 提示词 / 帧数 / 种子 | `scripts\jobs.json`（帧数 17k+5） |
| 过黑镜头权重 | `render.py`: `DIP` |
| 胶片感强度 | `render.py`: `LUT` / halation / streak / `VIG` / `GRAIN_TILES` |
| 字幕字号/位置 | `render.py`: `FONT`、`draw_sub` 的 `y` |
| 声源与场景对应 | `env_audio.py`: `PLACE` |
| 各类声源响度 | `mix.py`: `STEM_TARGET` |
| 配乐强弱弧线 | `mix.py`: `_intensity_env()` 的 `vals`、0.035 基准、0.55 闪避 |
| 母带响度 | `finish.py`: `loudnorm=I=-16:TP=-1.5` |

---

## 9. 已知限制

1. i2v 片段 1120×480 上采到 1920 宽，大屏细看略软（颗粒与胶片感有掩盖作用）。
2. 光流慢放在大位移区域可能有轻微 warp 痕迹；本片运动都很慢，实测不可察觉。
3. MOSS-TTS 克隆的是 Yunxi 试音样本的声纹，情绪幅度有限；`MOOD_RATE` 只做磁带级微调。
4. ACE-Step 配乐时长按提示词控制，`music_report.json` 已验证实际输出时长正确。
5. 本机 ffmpeg 旧（无 `xfade`），转场全部 Python 逐帧合成。
6. ComfyUI `output` 目录会累积历史文件，可定期清理。

---

## 10. 本机实测记录（当前成片）

### 10.1 成片参数

| 项 | 实测 |
|---|---|
| 文件 | `out\天地源_电影版_短片.mp4` |
| 时长 / 大小 / 码率 | 80.542 s / 75,055,783 B（≈ 75.1 MB）/ 7.46 Mbps |
| 画面 | H.264，1920×1080，24 fps，2.39:1 遮幅 |
| 音频 | AAC，48 kHz，立体声，192k |
| 母带 | I = -16.07 LUFS，TP = -1.91 dBTP，LRA = 4.4 |

### 10.2 各生成环节耗时（RTX 5060 Laptop 8GB / lowvram）

| 环节 | 规格 | 实测耗时 |
|---|---|---|
| 关键帧 ×11 | Z-Image-Turbo 1344×576 | 约 20–25 s/张 |
| S01 / S02 / S04 / S08 / S09 / S10 | 90 帧 1120×480 steps20 | 416–447 s/段 |
| S03 / S05 / S06 | 73 帧 | 321–331 s/段 |
| S07 / S11 | 124 帧 | 657–667 s/段 |
| clips 合计 | 11 段 | ≈ 81 min |
| 配乐 | ACE-Step 76s + 40s | 数分钟（详见 music_report.json） |
| 旁白 ×11 | MOSS-TTS 本地 | 总语音 56.9 s |
| 渲染 | 1933 帧全片 | 数分钟 |
| 母带封装 | loudnorm 2-pass + mux | < 1 min |

### 10.3 自检结果（`build\verify.py`）

* **镜头窗口响度**：-19.79 ~ -22.17 dBFS，句间电平一致。
* **2 s 窗 RMS 极差**：16.5 dB（含片头片尾淡入淡出，预期内）。
* **旁白存在性**：句内比句前留白高 6.4–21.3 dB；S08–S10 为 6.4–6.9 dB，
  因高潮段配乐/环境较强，但句内电平与其余镜头一致（-18.8 ~ -19.4 dBFS），11 句全部在位。
* **声源对位对比度**（场内 vs 场外，>12 dB 为明确）：
  steps 77.2 / insects 69.5 / paper 35.5 / glass 33.2 / fire 27.4 / drips 19.0 / crystal 15.5 dB。

### 10.4 与 v2 的差异一览

| 环节 | v2 进阶版 | v3 电影版 |
|---|---|---|
| 关键帧 | 沿用 v1 旧图 | Z-Image-Turbo 重绘 1344×576 |
| i2v | 832×480 / steps 16 | 1120×480 / steps 20 |
| 慢放 | 线性混帧 | Farneback 双向光流 |
| 画幅 | 16:9 全幅 | 2.39:1 遮幅 + 字幕入黑边 |
| 调色 | 固定 Lab 偏移 + 雾 | filmic LUT + halation + 拉丝眩光 + 色散 + 片门晃动 |
| 旁白 | edge-tts（联网） | MOSS-TTS 本地声纹克隆 |
| 配乐 | numpy 程序化 | ACE-Step 1.5 本地生成（可回退程序化） |

---

## 11. 版本记录

* **v1** `d:\models\sample\天地源\天地源_video`：静态关键帧 + OpenCV 推拉 + 单段 Yunyang 旁白。
* **v2** `d:\models\sample\天地源\天地源_进阶版`：Yunxi 分句韵律、本地 H3 i2v（832×480）、11 条 stem。
* **v3（电影版，本目录）**：全流程 100% 本地；Z-Image 重绘 + H3 高分辨率 i2v + 光流慢放 +
  2.39:1 遮幅与胶片洗印感 + MOSS-TTS 克隆旁白 + ACE-Step 配乐。
