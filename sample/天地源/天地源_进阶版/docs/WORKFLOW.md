# 天地源 · 进阶版 —— 工作流、参数与复现手册

> 本片是把 `d:\models\sample\天地源\片段-天地源.docx`（第一人称散文）做成的约 72 秒短片。
> 进阶版只针对上一版（`d:\models\sample\天地源\天地源_video`）被指出的三个问题重做：
>
> 1. **旁白生硬、不像真人** → 换音色 + 分句韵律 + 近场话筒链
> 2. **不像动画，只有图片缩放** → 本地 ComfyUI 图生视频（真实运动）+ 慢镜重定时
> 3. **环境音对不上、氛围弱** → 11 条独立声源 stem，按镜头位置自动推子，关键动作对位
>
> 所有产物、脚本、参数、提示词都在本目录内，可按第 7 节顺序逐步重跑。

---

## 1. 目录结构

```
d:\models\sample\天地源\天地源_进阶版\
├─ images\            11 张关键帧（沿用 v1 的美术，作为图生视频的起点）
├─ clips\             本地 ComfyUI 生成的 11 段动态片段 + 同名 .json（参数留档）
├─ audio\
│  ├─ lines\          逐句旁白 line01..11.wav（分句合成后拼接、做过话筒链）
│  ├─ stems\          11 条环境音 stem：wind/leaves/city/steps/glass/crystal/
│  │                  fire/paper/insects/drips/bell
│  ├─ mix.wav         混音总线（未做母带）
│  └─ master.wav      母带（-16 LUFS / TP -1.5）
├─ build\
│  ├─ tts_report.json 每句旁白的分句文本、时长、逐句 rate/pitch
│  ├─ timeline.json   镜头时长、起点、旁白入点、慢放倍率
│  ├─ stems_report.json
│  ├─ video_noaudio.mp4  合成画面（1080p24，CRF20）
│  ├─ test.mp4        单镜头自检片
│  └─ verify.py       成片自检（镜头窗口响度、stem 对位、旁白存在性）
├─ out\               成片：天地源_进阶版_短片.mp4
├─ scripts\           全部可执行脚本（见第 5 节）
└─ docs\              本手册
```

---

## 2. 技术路线

```
关键帧(11) ──┐
             ├─► ComfyUI / MiniMax-H3 图生视频  ─► clips\s01..s11.mp4 (832x480,24fps,3~5s)
散文文本 ────┤                                                   │
             └─► edge-tts 分句韵律 ─► line*.wav ─┐               │
                                                 ▼               ▼
                                        timeline.json ──► render.py（慢放重定时/调色/雾/颗粒/字幕/叠化）
                                                                 │
   env_audio.py（11 条 stem，按镜头推子）──┐                      ▼
   mix.py（程序化配乐 + 闪避 + 自动标定）──┴──────────► mix.wav ─► finish.py（loudnorm 2-pass + 封装）─► out\*.mp4
```

---

## 3. 环境（已在本机验证）

| 项 | 值 |
|---|---|
| GPU | RTX 5060 Laptop，8 GB 显存，驱动 580.x |
| RAM | 32 GB |
| ComfyUI | `D:\models\ComfyUI`，服务 `http://127.0.0.1:8188` |
| ComfyUI Python | **`D:\models\.venv\Scripts\python.exe`**（系统 python 缺 pyyaml/alembic，不能用来启动） |
| torch | 2.14.0+cu130 |
| 视频模型 | MiniMax-H3 i2v：`minimax_h3_fl2v_int8` (19.5 GB) + `qwen3vl_32b_nvfp4` (14.6 GB) + `minimax_h3_video_vae_fp16` (4.85 GB) |
| 工作流 | `D:\models\scripts\comfyui\minimax-h3\workflow_i2v.json`（ComfyUI 原生节点） |
| 客户端 | `D:\models\scripts\comfyui\comfy_client.py`（上传图 / 提交 / 轮询 / 取回） |
| TTS | edge-tts，音色 `zh-CN-YunxiNeural` |
| 合成 | Python 3.12 + numpy/scipy/opencv/Pillow |
| ffmpeg | `C:\Program Files\EVCapture\ffmpeg.exe`（2019 版，**没有 xfade 滤镜**，转场全部自己算） |

### 3.1 启动 ComfyUI 前修过一次依赖

`.venv` 里 `huggingface-hub==1.33.0` 与 `transformers==4.57` 冲突，ComfyUI 起不来。已固定：

```powershell
& "D:\models\.venv\Scripts\python.exe" -m pip install "huggingface-hub==0.35.3"
```

> 若以后装了别的库把 hub 又升到 1.x，ComfyUI 会报
> `huggingface-hub>=0.34.0,<1.0 is required`，按上面一行降回即可。

---

## 4. 分镜与时间轴（当前成片）

| # | 镜头 | 画面 | 旁白 | 镜长 | 起点 | 旁白入点 | 动态来源 |
|---|---|---|---|---|---|---|---|
| 1 | S01 | 街角全景，湿地面 | 天色渐暗…一边热闹，一边冷清。 | 8.06 | 0.00 | 1.55 | s01 |
| 2 | S02 | 枯藤小道 | 枯藤缠绕的小道…白花岗岩圆亭。 | 6.25 | 7.34 | 8.29 | s02 |
| 3 | S03 | 亭内柱廊 | 我迈步进入，没有人注意到我。 | 4.30 | 12.86 | 13.66 | s03 |
| 4 | S04 | 石子阵纹 | 石子隐约铺出岔路…好似阵法。 | 7.16 | 16.45 | 17.35 | s04 |
| 5 | S05 | 玻璃穹顶 | 抬头，圆形的玻璃顶… | 6.82 | 22.89 | 23.74 | s05 |
| 6 | S06 | 穹顶特写 | 玻璃好似并不存在。“虚无”… | 6.53 | 28.99 | 29.89 | s06 |
| 7 | S07 | 三界（光柱） | 天地园，链接天地…另一头是人间。 | 10.98 | 34.80 | 35.80 | s07 |
| 8 | S08 | 雨后林荫道 | 人间水晶般完美…唯一的声音。 | 6.68 | 45.06 | 46.01 | s08 |
| 9 | S09 | 地狱走廊 | 地狱并不可怕…求而不得。 | 6.44 | 51.02 | 52.02 | s09 |
| 10 | S10 | 天堂/纸片 | 而天堂最悲苦…碎裂的纸。 | 8.04 | 56.75 | 57.80 | s10 |
| 11 | S11 | 夜幕空亭 | 二〇二二年三月六日，夜幕降临时。 | 8.37 | 64.07 | 65.27 | s11 |

总长 **72.43 s**，帧率 24，1920×1080，镜头间 0.72 s 叠化。

---

## 5. 脚本清单（`scripts\`）

| 文件 | 作用 | 是否可单独重跑 |
|---|---|---|
| `config.py` | 所有路径、镜头表、音色、LEAD/TAIL 节奏 | — |
| `jobs.json` | 11 个镜头的图生视频提示词、时长、分辨率、步数、种子 | — |
| `01_start_comfyui.ps1` | 启动本地 ComfyUI 并等待就绪 | 是 |
| `comfy_i2v.py` | 调 ComfyUI 生成动态片段，写 sidecar json | 是 |
| `build_tts.py` | 分句合成旁白 + 话筒链 | 是 |
| `timeline.py` | 用旁白实际时长推导时间轴 | 是（依赖 tts_report） |
| `env_audio.py` | 合成 11 条环境音 stem | 是（依赖 timeline） |
| `render.py` | 画面合成（慢放、调色、雾、颗粒、字幕、转场） | 是 |
| `mix.py` | 旁白 + 配乐 + stem 混音，自动标定、闪避 | 是 |
| `finish.py` | 两遍 loudnorm + 封装 | 是 |
| `run_all.ps1` | 一键按顺序跑完 | — |
| `tts_test.py` | 音色对比试音（5 个音色的基频/能量动态指标） | 是 |

---

## 6. 设计细节（为什么这么做）

### 6.1 旁白：为什么不再整句合成

上一版用 `zh-CN-YunyangNeural`（新闻播报音色）整句合成、统一 `rate -6%`，所以像播音。
进阶版：

* **换音色**：先做 5 音色对比（`tts_test.py` 量化基频标准差、能量动态、语速、停顿比），
  `Yunxi` 的语调起伏最好，`Yunyang` 虽指标不低但听感最“播报”，弃用。
* **分句韵律**：每句按标点切成 2~5 个小句，**逐句**给 `rate/pitch/volume`；
  句内还有“递降”——越靠后的分句音高略低、语速略慢，像把话收住。
* **情绪档位**：`calm / lift / low / void` 四档（见 `config.py` 的 `LINE_MOOD`）。
  “虚无”“天堂”用 `low/void`：更慢、更低、更轻。
* **停顿**：`，`0.24s、`。`0.40s、`：`0.32s……长停顿里按 1/3 概率放一次极轻换气（-42 dBFS 左右）。
* **近场话筒链**：高通 85 Hz → 2.2–3.4 kHz +2.5 dB（存在感）→ 6.5 kHz 以上轻衰减（齿音）→
  3:1 压缩（-26 dBFS 阈值）→ 0.55 s 短混响（湿 10%）。
  这一条让“合成音”有了近讲录音的空间感。
* **响度统一**：每个小句按语音 RMS 归一到 0.105，混音时整句再归一到 0.112 → 句间不再忽大忽小。

### 6.2 动态：为什么用本地 ComfyUI + 慢放

* 云端 `GenerateVideo` 单次费用高（已被否），改用本机 ComfyUI 的 MiniMax-H3 图生视频。
* H3 的帧数受网格约束：`length = 17k + 5`（5/22/39/56/73/90/107/124）。
  73 帧 = 3.04 s，90 帧 = 3.75 s，124 帧 = 5.17 s。
* 镜头需要 4~11 s，所以把 3~5 s 的片段**时间重映射**到目标时长（1.5~2.3× 慢放），
  帧间做线性混合，得到慢镜+轻微运动模糊，不出现跳帧。
  慢放在这种散文片里是加分项，也让风的运动更可读。
* 每个镜头的提示词都强调：**保持构图/建筑不变**、写实物理运动（风、雾、云、火星、纸片、
  水洼倒影、灯闪）、**不加文字、不加人物（S09 只保留原有背影）**。
* 生成结果实测：832×480、24 fps、steps 16（8 GB 显存 + lowvram）。单段耗时
  73 帧 ≈ 186–191 s，90 帧 ≈ 231–241 s，124 帧 ≈ 361 s。
* 片段自带的 H3 原生音轨**全部丢弃**，音效另做（见 6.3）。

### 6.3 声音：镜头 → 声源对应表

| 镜头 | 地点 | 主要声源 |
|---|---|---|
| S01 全景 | out | 风 1.0、枝叶 0.85、远处车流 0.55、虫鸣 0.45、水滴 0.30 |
| S02 小道 | path | 风 0.95、枝叶 0.90、车流 0.35、**石子脚步 0.55**（3 步） |
| S03 亭内 | pavilion | 风 0.42、**脚步 0.38**（4 步）、玻璃/铁件 0.50、水滴 0.10 |
| S04 石子 | pavilion | 同亭内，弱化 |
| S05/S06 穹顶 | pavilion | 风 0.42、玻璃铁件 0.50 |
| S07 三界 | three | 风 0.70、晶体 0.55、玻璃 0.22、**玻璃钟**（光柱 1.15 s 处） |
| S08 人间 | world | 极轻：风 0.28、远处城市 0.28、晶体 0.30 |
| S09 地狱 | hell | **火 0.85**、火星爆裂 26 次、风 0.38 |
| S10 天堂 | heaven | 风 0.68、**纸片翻飞 0.55**（9 次）、晶体 0.32 |
| S11 结尾 | out | 风 1.05、虫鸣、夜雾、**结尾玻璃钟**（-4.4 s） |

实现要点：
* 每个 stem 独立成 48 kHz 立体声文件，**按镜头 place 生成增益曲线**，边界 0.45 s 交叉、再 0.55 s 高斯平滑，
  所以换镜头时声音是“跟着画面推”的，不会突然断。
* 单发事件（脚步、水滴、玻璃响、虫鸣、纸、火星、钟）按**绝对时间**排布，和旁白入点对齐。
* 混音时每条 stem 用 **95 分位场内 RMS 自动标定**到目标响度（例如风 0.013、火 0.013），
  避免“只在 6 秒镜头里出现”的声源被算成整片平均而爆掉。
* 旁白出现时：音乐 -55%、环境音 -22%（平滑包络 0.55 s）。

### 6.4 配乐

程序化生成（numpy），不依赖外部素材：Dm(add9) → Bb maj7 → F add9 → Gm → Am 循环，
低音持续音 + 双 detune 弦垫 + 稀疏钢琴点 + 空气噪声床，3.4 s 混响。
强度按镜头给（三界/地狱 0.9+，人间 0.46，结尾 0.36），并做旁白闪避。

### 6.5 画面统一

* **调色**：以 5 个园景镜头的中位 Lab 统计为基准，每镜头算一组**固定**偏移/增益后整段套用
  （不是逐帧自适应，所以不会闪）；再叠一层统一 film grade（轻微降饱和、暗部偏青、高光偏暖）。
* **氛围**：两层不同尺度的噪声雾按镜头强度漂移；胶片颗粒每帧轮换 10 张预生成噪声；暗角 + 底部压暗保证字幕可读。
* **字幕**：STSONG 42px，按**绝对时间**跟随旁白入点淡入淡出（0.35 s），不再按镜头切片。
* **转场**：默认 0.72 s 叠化；S06（虚无）、S07（三界）、S10（天堂）叠加轻微过黑（0.18~0.36），避免硬切。
  由于本机 ffmpeg 没有 `xfade`，叠化是在 Python 里逐帧混合完成的。

### 6.6 响度

`mix.wav` → 两遍 `loudnorm`（先测再打）到 **I=-16 LUFS / TP=-1.5 dBTP / LRA=11**，线性模式，
最后 aac 192k 封装。

---

## 7. 复现步骤（可单独重跑任意一步）

在 `d:\models\sample\天地源\天地源_进阶版` 下打开 PowerShell：

### 7.1 启动 ComfyUI

```powershell
.\scripts\01_start_comfyui.ps1
```

看到 `ComfyUI 就绪：http://127.0.0.1:8188` 即可。

### 7.2 生成/重生成动态片段

```powershell
& "D:\models\.venv\Scripts\python.exe" .\scripts\comfy_i2v.py --all          # 缺哪个补哪个
& "D:\models\.venv\Scripts\python.exe" .\scripts\comfy_i2v.py --job S07 --force
& "D:\models\.venv\Scripts\python.exe" .\scripts\comfy_i2v.py --job S01 --length 90 --res 832x480 --steps 16
```

* 产物：`clips\sNN.mp4` + `clips\sNN.json`（含提示词、分辨率、帧数、步数、种子、耗时、prompt_id）。
* 想改画面：编辑 `scripts\jobs.json` 里对应镜头的 `prompt` / `length` / `seed`，再 `--job Sxx --force`。
* 分辨率必须是 32 的倍数；帧数必须是 17k+5。

### 7.3 旁白

```powershell
python .\scripts\build_tts.py
```

产物 `audio\lines\line01..11.wav`、`build\tts_report.json`。约 1–2 分钟（30+ 次 TTS 请求，需联网）。
改语气：`config.py` 的 `LINE_MOOD`；改音色：`config.py` 的 `VOICE`（可先跑 `tts_test.py` 对比）。

### 7.4 时间轴

```powershell
python .\scripts\timeline.py
```

改节奏：`config.py` 的 `LEAD` / `TAIL`（句子前后留白）、`XFADE`（叠化时长）。

### 7.5 环境音

```powershell
python .\scripts\env_audio.py
```

改声源与镜头的对应：`env_audio.py` 顶部 `PLACE` 表；改单发事件位置：同文件事件段。

### 7.6 画面合成

```powershell
python .\scripts\render.py
```

约 3–5 分钟（1738 帧）。单独自检：

```powershell
$env:TEST="1"; python .\scripts\render.py; Remove-Item Env:TEST
```

### 7.7 混音

```powershell
python .\scripts\mix.py
```

改层级：`mix.py` 的 `STEM_TARGET`；改闪避深度：`music_duck / sfx_duck`。

### 7.8 母带与封装

```powershell
python .\scripts\finish.py
```

产物：`out\天地源_进阶版_短片.mp4`。

### 7.9 一键

```powershell
.\scripts\run_all.ps1              # 已有片段会跳过
.\scripts\run_all.ps1 -ForceVideo  # 重生成全部片段
.\scripts\run_all.ps1 -SkipVideo   # 只重做声音与画面
```

---

## 8. 参数速查

| 想改什么 | 改哪里 |
|---|---|
| 音色 / 情绪 / 语速 | `config.py`: `VOICE`, `LINE_MOOD`；`build_tts.py`: `MOOD` 表 |
| 句子前后留白 | `config.py`: `LEAD`, `TAIL` |
| 叠化时长 | `config.py`: `XFADE` |
| 镜头画面提示词 | `scripts\jobs.json` 的 `prompt` |
| 片段时长 | `jobs.json` 的 `length`（17k+5） |
| 雾/颗粒/暗角强度 | `config.py` 的 `fog`；`render.py` 的 `VIG`、`GRAIN` |
| 字幕字号/位置 | `render.py`: `FONT`、`SUB_Y` |
| 画面亮度弧线 | `render.py`: `TARGET_LS` |
| 声源与场景对应 | `env_audio.py`: `PLACE` |
| 各类声源响度 | `mix.py`: `STEM_TARGET` |
| 配乐强弱 | `mix.py`: `make_music()` 里的 `vals`、0.035 基准、`0.55 * music_duck` |
| 母带响度 | `finish.py`: `loudnorm=I=-16:TP=-1.5` |

---

## 9. 已知限制

1. 片段分辨率 832×480，上采到 1080p；大屏细看会略软（有机理与颗粒掩盖，整体可接受）。
   想要更锐：把 `jobs.json` 的 `res` 改成 `1088x608` 再重生成（显存 8 GB 下会慢约 1.6×）。
2. H3 的时长受网格限制，最长的 S07/S11 用 90/124 帧再慢放，动作比实拍慢，属风格化选择。
3. 本机 ffmpeg 很旧（无 `xfade`），所有转场为 Python 逐帧合成；若要更复杂的转场需换新版 ffmpeg。
4. 配乐是程序化生成，不是商用曲库；如需真实配乐，可把 `audio\music.wav` 换掉并让 `mix.py` 读取它。
5. `clips\*.json` 记录了每次生成的 prompt_id 与随机种子，但 ComfyUI 的 `output` 目录里仍会留有历史文件，可定期清理。

---

## 10. 本机实测记录（当前成片）

### 10.1 成片参数

| 项 | 实测 |
|---|---|
| 文件 | `out\天地源_进阶版_短片.mp4` |
| 时长 / 大小 / 码率 | 72.542 s / 40,636,255 B（≈ 40.6 MB）/ 4.48 Mbps |
| 画面 | H.264，1920×1080，24 fps |
| 音频 | AAC，48 kHz，立体声 |
| 母带 | I = -16 LUFS，TP = -1.5 dBTP，LRA = 11 |

### 10.2 片段生成耗时（832×480 / steps 16 / lowvram）

| 帧数 | 原始时长 | 实测耗时 |
|---|---|---|
| 73 | 3.04 s | 186–191 s |
| 90 | 3.75 s | 231–241 s |
| 124 | 5.17 s | 361 s |

### 10.3 响度与对位验证（`build\verify.py` 的结果）

* **镜头窗口响度**：11 个镜头窗口 RMS 为 **-20.40 ~ -22.60 dBFS**，极差仅 **2.2 dB**
  （上一版句间忽大忽小的问题已解决）。
* **2 s 窗 RMS 极差**：18.6 dB（包含片头片尾的淡入淡出，属预期）。
* **旁白存在性**：每句“句内”比“句前留白”高 **10.7–19.5 dB**，11 句全部在位、无漏句。
* **声源对位对比度**（该声源在场 vs 不在场）：

| stem | 对比度 | stem | 对比度 |
|---|---|---|---|
| steps（脚步） | 77.7 dB | fire（火） | 27.0 dB |
| insects（虫鸣） | 70.2 dB | glass（玻璃/铁件） | 18.4 dB |
| paper（纸片） | 31.1 dB | crystal（晶体） | 15.3 dB |
| drips（水滴） | 15.1 dB | | |

全部 > 12 dB，说明“画面到哪、声音跟到哪”是清楚的。

### 10.4 各 stem 最终场内电平（旁白约 -20 dBFS）

| stem | dBFS | stem | dBFS |
|---|---|---|---|
| wind | -35.3 | paper | -35.9 |
| leaves | -39.7 | insects | -38.4 |
| city | -37.6 | drips | -39.4 |
| steps | -35.2 | bell | -33.2 |
| glass | -38.5 | fire | -33.6 |
| crystal | -37.9 | | |

---

## 11. 版本记录

* **v1** `d:\models\sample\天地源\天地源_video`：静态关键帧 + OpenCV 缓动推拉 + 单段 Yunyang 旁白 + 单一氛围噪声。
* **v2（进阶版，本目录）**：
  * 旁白：Yunxi + 分句韵律 + 停顿 + 话筒链 + 逐句响度归一
  * 画面：本地 ComfyUI MiniMax-H3 图生视频（11 段真实运动）+ 慢放重定时 + 固定色彩变换
  * 声音：11 条环境音 stem，按镜头自动推子，关键动作对位；配乐加入强度弧线与闪避
  * 工程：所有脚本、提示词、参数、中间产物落盘，可按第 7 节逐步重跑
