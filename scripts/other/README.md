# 可移植运行样例 · other（非 llama.cpp / 非 ComfyUI 模型）

本目录集中存放**不属于 llama.cpp 与 ComfyUI 那批模型**的运行样例脚本，统一遵循：

- 模型根目录通过环境变量 `MODEL_ROOT` 覆盖，默认 `d:\models\models`；
- 输出默认写到 `MODEL_ROOT` **同级目录**下的 `output/other/<案例名>/`（默认即 `d:\models\output\other\...`），可用各自的 `--out` / `--out-dir` 覆盖；
- 脚本顶部都带中文 docstring（用途 / 依赖 / 示例命令）；
- 全部使用环境变量 + 相对拼接路径，**不硬编码到具体项目的 Temp 目录**。

## 目录

| 脚本 | 用途 | 主要依赖 |
| --- | --- | --- |
| `tts_moss.py` | MOSS-TTS 中文语音合成（可选参考音频克隆音色） | torch / transformers / torchaudio / soundfile |
| `music_qc.py` | MOSS-Music-8B 音乐质检（调性/配器/情绪/风格），4bit NF4 加载 | torch / transformers / bitsandbytes / soundfile / numpy |
| `asr_diarize.py` | 语音转写 + 说话人分离（VAD→ASR→声纹聚类→可选字级对齐） | funasr / torch / torchaudio / soundfile / numpy / scikit-learn / qwen_asr |

统一 Python 解释器：`d:\models\.venv\Scripts\python.exe`（上述依赖均已安装）。

## 模型位置（默认，均相对 `MODEL_ROOT`）

| 用途 | 路径 |
| --- | --- |
| MOSS-TTS 主干 | `audio/MOSS-TTS/`（`model.safetensors` + `mossttsrealtime/` 包 + tokenizer） |
| MOSS-TTS 声码器 | `audio/MOSS-Audio-Tokenizer/`（双分片 safetensors，`trust_remote_code`） |
| 音乐理解 | `music/MOSS-Music-8B/`（bf16 权重，运行时 4bit NF4 量化） |
| ASR | `audio/Qwen3-ASR-0.6B/` |
| 声纹 | `audio/campplus/` |
| 字级对齐 | `audio/Qwen3-ForcedAligner-0.6B/` |
| VAD | `silero_vad`（FunASR 模型库按名加载，本机已有缓存） |

## 命令行示例

### 1) TTS

```powershell
# 默认音色，输出到 output/other/tts/tts_<hash>.wav
python tts_moss.py --text "你好，这是本地语音合成测试。"

# 指定输出文件
python tts_moss.py --text "记住这个颜色。" --out line.wav

# 参考音频克隆音色
python tts_moss.py --text "记住这个颜色。" --ref-audio ref_father.wav
```

### 2) 音乐质检

```powershell
python music_qc.py song.wav
python music_qc.py song.wav --prompt "请描述这段音乐的调性、配器和情绪。" --out result.txt
# 避免复读可调采样参数
python music_qc.py song.wav --temperature 0.6 --repetition-penalty 1.15
```

### 3) 转写 + 说话人分离

```powershell
python asr_diarize.py dialogue.wav                       # 输出到 output/other/asr/dialogue.{json,srt}
python asr_diarize.py dialogue.wav --speakers 3          # 指定说话人数
python asr_diarize.py dialogue.wav --align --split-gap 0.5   # 字级时间戳 + 段内说话人细化
```

## 实测状态（如实标注）

| 脚本 | 语法检查 | `--help` 冒烟 | 真实推理实测 |
| --- | --- | --- | --- |
| `tts_moss.py` | 通过 | 通过 | **未在本机重跑** |
| `music_qc.py` | 通过 | 通过 | **未在本机重跑**（逻辑移植自已跑通的项目版） |
| `asr_diarize.py` | 通过 | 通过 | **未在本机重跑**（逻辑移植自已跑通的项目版） |

说明：

- 三个样例均通过 `python -m py_compile` 语法检查，且 `--help` 正常输出。
- **真实推理未实测**：加载这些模型会占用 6~8GB 显存且耗时很长，本目录样例仅做语法 + `--help` 冒烟测试。
- 逻辑出处（已在原项目中实际运行过，本次为"通用化"改写，去掉了硬编码路径）：
  - `tts_moss.py` ← `d:\models\sample\铁锈海的女儿\scripts\gen_speech.py`（项目版 MOSS-TTS 合成，已跑通）；
    并修正了旧脚本 `d:\models\scripts\moss_tts.py` 中的**字符损坏**（该文件磁盘内容把所有小写 `m` 错成 `o`，且使用了已不存在的旧路径 `D:\models\models-gguf`）。
  - `music_qc.py` ← `...\scripts\analyze_music.py`（4bit NF4 加载 + 多处兼容性修复，已跑通）。
  - `asr_diarize.py` ← `...\scripts\diarize_transcribe_funasr.py` 与 `test_forced_aligner.py`（含 ForcedAligner 绕过 FunASR 缺陷的独立调用，已跑通）。
- 因此样例**复用**了已被验证的调用方式与兼容性修复（torchaudio.load 兜底、MOSS-Music 的 `audio_input_mask`/float16 修复、configuration 的 AttrDict 补丁），但**未逐条重跑**，请以首次实跑结果为准。

## 迁移到另一台电脑需要改什么

1. **安装依赖**：确保目标机的 Python 环境（建议独立 venv）装齐上表依赖，尤其 `bitsandbytes`（MOSS-Music 4bit 必需）与 `qwen_asr`（`--align` 必需）。
2. **模型目录结构**：目标机的模型目录按上表保持**相同的相对结构**（`audio/...`、`music/...`）。若模型根不是 `d:\models\models`，设置环境变量即可，无需改代码：
   ```powershell
   $env:MODEL_ROOT = "E:\ai\models"     # 模型根
   # 输出默认取 $env:MODEL_ROOT 的同级 output/other/；如需自定义：
   $env:OUTPUT_ROOT = "E:\ai\output"
   ```
3. **GPU / 显存**：默认自动选择 `cuda`，无 GPU 自动回退 `cpu`（TTS/ASR）；MOSS-Music 走 `device_map="auto"`（4bit 需 GPU）。显存不足时可先 `--device cpu`（TTS/ASR）。
4. **MOSS-TTS 包布局**：若模型目录是 HF 平铺 py 文件，脚本会自动组装 `mossttsrealtime/` 包；正常下载已含该子包时无需处理。
5. **可选模型**：`asr_diarize.py` 的 `--model` / `--model-path` / `--vad-model` / `--spk-model-path` / `--aligner-path` 均可按目标机实际路径/模型 ID 覆盖。
6. **路径分隔符**：脚本内部一律用 `pathlib` 拼接，跨平台无需改动；Windows 下示例命令按 PowerShell 书写。

## 已知限制

- `tts_moss.py` 的 `--ref-text`（参考音频对应文本）会被接收但**当前不参与计算**：现使用的 Realtime inferencer 仅取参考音频的音色，不消费参考文本。如未来换成需要 ref_text 的接口，再接入即可。
- `asr_diarize.py` 使用 silero-VAD（对短静音更敏感）；如需 `fsmn-vad`，用 `--vad-model fsmn-vad` 覆盖。
- `music_qc.py` 仅输出文本分析结果，不做音频评分或自动剪辑。
