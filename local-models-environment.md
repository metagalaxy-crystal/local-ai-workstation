# 本地模型运行环境手册（RTX 5060 Laptop / 8GB + 32GB）

> 目标：在 `D:\models` 下运行一套面向 8GB 显存 + 32GB 内存优化的本地推理与生成环境，覆盖文本对话、多模态理解、文生图、文生视频、音乐生成质检、语音合成、语音转写与说话人分离。
> 更新日期：2026-10-15 ｜ 硬件：RTX 5060 Laptop (Blackwell sm_120, 8GB GDDR7) / 32GB RAM

---

## 1. 环境基线

| 组件 | 版本/路径 | 备注 |
|------|----------|------|
| CUDA Toolkit | 13.2 (V13.2.78) | 原生支持 Blackwell sm_120 |
| 驱动 | 616.64 / CUDA UMD 13.4 | — |
| Visual Studio | VS 18 (2026) Community | MSVC 编译链 |
| CMake | 随 VS 安装 | — |
| Python venv | `D:\models\.venv` | llama.cpp / other 脚本共用 |
| ComfyUI Python | 系统 python | ComfyUI 自带依赖 |
| GPU | RTX 5060 Laptop, 8151 MiB | — |

> **Blackwell 架构 (sm_120) 必须用 CUDA 12.8+/13.x 构建的 llama.cpp**，旧版二进制会报 `no kernel image`。本机已用 CUDA 13.2 源码编译。

---

## 2. 核心设计思路

**用 32GB 内存换 8GB 显存**：通过 GGUF 量化、MoE 专家层 CPU 卸载、KV Cache 量化，在有限硬件上最大化模型能力。

| 任务域 | 运行引擎 | 模型位置 |
|--------|----------|----------|
| 文本对话 / 多模态理解 | llama.cpp `llama-server`（OpenAI 兼容 HTTP） | `models\text\` |
| 文生图 / 文生视频 / 音乐 | ComfyUI（`/prompt` 图任务队列） | `models\image\` `models\video\` `models\music\` |
| 语音合成 / 音乐质检 / ASR+分离 | 各模型自己的 Python 推理栈 | `models\audio\` `models\music\MOSS-Music-8B\` |

---

## 3. 目录结构

```
D:\models\
├── models\                        # 模型根目录（按业务领域归类）
│   ├── text\                      # llama.cpp 文本/多模态模型（GGUF）
│   │   ├── Nanbeige4.2-3B\
│   │   ├── LFM2.5-8B-A1B\
│   │   ├── DeepSeek-R1-0528-Qwen3-8B\
│   │   ├── Ornith-1.0-9B\
│   │   ├── Qwen3.6-35B-A3B\       # 含 mmproj
│   │   ├── MiniCPM-V-4_6\         # 含 mmproj
│   │   └── Qwen2.5-VL-7B\         # 含 mmproj
│   ├── image\                     # ComfyUI 文生图模型
│   │   ├── Z-Image\               # GGUF 主干 + Qwen3-4B 编码器 + ae VAE
│   │   ├── ERNIE-Image-Turbo\     # GGUF + Ministral-3B + Flux2 VAE
│   │   └── Anima\                 # safetensors 三件套
│   ├── video\                     # ComfyUI 视频模型
│   │   └── MiniMax-H3\            # int8 主干 + 32B 编码器 + 双 VAE
│   ├── music\                     # 音乐模型
│   │   ├── ACE-Step-1.5\          # ComfyUI 文生音乐（DiT + 双 Qwen 编码器）
│   │   └── MOSS-Music-8B\         # 音乐质检（4bit NF4 加载）
│   └── audio\                     # 语音相关模型
│       ├── MOSS-TTS\              # 中文语音合成（含声码器 MOSS-Audio-Tokenizer）
│       ├── Qwen3-ASR-0.6B\        # 语音转写
│       ├── Qwen3-ForcedAligner-0.6B\  # 字级时间戳对齐
│       ├── campplus\              # 声纹嵌入
│       ├── fsmn-vad\              # VAD（备用，默认用 silero-vad）
│       └── MOSS-Audio-Tokenizer\  # MOSS-TTS 声码器
│
├── llama.cpp\                     # 源码 + 构建产物
│   ├── src\                       # git clone
│   └── build\bin\Release\         # llama-server.exe 等
│
├── ComfyUI\                       # 视频/图像/音乐生成框架
│   └── custom_nodes\ComfyUI-GGUF\ # 加载 GGUF 模型
│
├── scripts\                       # 运行样例（按引擎+模型两级拆分）
│   ├── config.py                  # 公共路径配置（环境变量可覆盖）
│   ├── llama_cpp\                 # 7 个模型目录，每个含 start.bat/chat.bat/README
│   │   ├── models.json  start_server.py  chat.py  vlm_test.py  run.py
│   │   └── {nanbeige,lfm,deepseek-r1,ornith,qwen36,minicpmv,qwen25vl}\
│   ├── comfyui\                   # 5 个模型目录，每个含 workflow.json/run.bat/README
│   │   ├── comfy_client.py  run_image.py  run_video.py  run_music.py  run.py
│   │   └── {zimage,ernie,anima,minimax-h3,acestep}\
│   └── other\                     # 非 llama.cpp / 非 ComfyUI 模型
│       ├── tts_moss.py  music_qc.py  asr_diarize.py  README.md
│
├── output\                        # 所有样例产物统一输出目录
│   ├── llama_cpp\chat\  llama_cpp\vlm\
│   ├── comfyui\image_*  comfyui\video_h3  comfyui\music_acestep\
│   └── other\tts\  other\music\  other\asr\
│
├── .venv\                         # uv 虚拟环境
├── 铁锈海的女儿\                  # 小说→分镜→文生图→图生视频→配音/BGM 全链路案例
└── local-models-environment.md    # 本文件
```

---

## 4. llama.cpp 构建（已完成）

### 4.1 为什么必须源码编译
Blackwell sm_120 极新，官方 Release 预编译二进制多数仍是 CUDA 12.x / sm_90 以下，直接运行会报 `CUDA error: no kernel image is available for execution on the device`。已用本机 CUDA 13.2 自行编译，锁定 `CUDA_ARCHITECTURES=120`。

### 4.2 构建命令

```powershell
cd D:\models
git clone https://github.com/ggerganov/llama.cpp.git llama.cpp\src
cd D:\models\llama.cpp\src

cmake -S . -B ..\build `
  -G "Visual Studio 18 2026" -A x64 `
  -DCMAKE_BUILD_TYPE=Release `
  -DGGML_CUDA=ON `
  -DCMAKE_CUDA_ARCHITECTURES=120 `
  -DGGML_NATIVE=ON `
  -DGGML_CUDA_F16=ON `
  -DGGML_CUDA_FORCE_MMQ=ON

cmake --build ..\build --config Release -j
```

产物：`D:\models\llama.cpp\build\bin\Release\llama-server.exe`

---

## 5. 模型清单

### 5.1 文本 / 多模态（llama.cpp，`models\text\`）

| key | 模型 | 量化 | 体积 | 上下文 | 思考 | mmproj | 卸载策略 | 用途 |
|-----|------|------|------|--------|------|--------|----------|------|
| `nanbeige` | Nanbeige4.2-3B | Q4_K_M | 2.4 GB | 32K | 可选 | — | 全量上 GPU，KV q4_0 | 分镜草稿、批量改写、长文摘要 |
| `lfm` | LFM2.5-8B-A1B | Q4_K_M | 4.8 GB | 16K | 无 | — | 全量上 GPU（激活仅 1B） | 通用对话、分镜路由 |
| `deepseek-r1` | DeepSeek-R1-0528-Qwen3-8B | Q4_K_M | 4.7 GB | 32K | 默认开 | — | 全量上 GPU | 复杂推理、数学、思维链分析 |
| `ornith` | Ornith-1.0-9B-heretic-MTP | Q4_K_M | 5.4 GB | 32K | 可选 | — | 全量上 GPU，MTP 投机解码 | 代码、结构化输出 |
| `qwen36` | Qwen3.6-35B-A3B | Q4_K_M | 19.7 GB | 16K | 默认开 | 0.84 GB | `--n-cpu-moe 99` 专家留内存 | 质检、评测、图片+视频理解 |
| `minicpmv` | MiniCPM-V-4.6 | Q4_K_M | 0.5 GB | 8K | 可选 | 0.68 GB | 全量上 GPU | 看图说话、OCR、视频理解（主力） |
| `qwen25vl` | Qwen2.5-VL-7B-Instruct | Q4_K_M | 4.4 GB | 8K | 无 | 0.79 GB | 全量上 GPU | 图表/版面理解（备选） |

### 5.2 文生图（ComfyUI，`models\image\`）

| 目录 | 模型 | 量化 | 步数 | 分辨率 | 节点 |
|------|------|------|------|--------|------|
| `zimage` | Z-Image-Turbo | Q4_K_M GGUF | 8 | 1088×608 | ComfyUI-GGUF |
| `ernie` | ERNIE-Image-Turbo | Q4_K_M GGUF | 8 | 1024×1024 | ComfyUI-GGUF |
| `anima` | Anima v1.0 | safetensors | 30 | 832×1216 | 无 |

### 5.3 视频（ComfyUI，`models\video\`）

| 目录 | 模型 | 量化 | 能力 |
|------|------|------|------|
| `minimax-h3` | MiniMax H3 | int8 | 文生视频 / 图生视频 + 原生音效 |

### 5.4 音乐（`models\music\`）

| 目录 | 模型 | 引擎 | 用途 |
|------|------|------|------|
| `ACE-Step-1.5` | ACE-Step 1.5 | ComfyUI | 文生音乐 / BGM（48kHz） |
| `MOSS-Music-8B` | MOSS-Music-8B | Python（4bit NF4） | 音乐质检（调性/配器/情绪/风格） |

### 5.5 语音（`models\audio\`）

| 模型 | 用途 |
|------|------|
| MOSS-TTS + MOSS-Audio-Tokenizer | 中文语音合成（可选参考音频克隆音色） |
| Qwen3-ASR-0.6B | 语音转写 |
| Qwen3-ForcedAligner-0.6B | 字级时间戳对齐 |
| campplus | 声纹嵌入（说话人聚类） |
| silero-vad | 语音分段（默认） / fsmn-vad（备用） |

---

## 6. 运行方式总览

所有样例的产物统一输出到 `D:\models\output\`。模型目录只做转调，引擎脚本在引擎根目录共用。

### 6.1 公共配置层

`scripts\config.py` 集中解析所有路径，**每一项都可用环境变量覆盖**：

| 环境变量 | 默认值 | 含义 |
|----------|--------|------|
| `MODEL_ROOT` | `d:\models\models` | 模型根目录 |
| `LLAMA_DIR` | `d:\models\llama.cpp` | llama.cpp 目录 |
| `COMFY_DIR` | `d:\models\ComfyUI` | ComfyUI 目录 |
| `OUTPUT_ROOT` | `d:\models\output` | 产物输出根目录 |
| `COMFY_HOST` | `http://127.0.0.1:8188` | ComfyUI 服务地址 |
| `SAMPLE_PY` | `d:\models\.venv\Scripts\python.exe` | llama.cpp / other 用解释器 |
| `COMFY_PY` | `python` | comfyui / .bat 用解释器 |

### 6.2 llama.cpp 文本/多模态

```powershell
cd D:\models\scripts

# 双击派：进模型目录双击 start.bat，再开一个窗口双击 chat.bat
# 命令行派：
llama_cpp\nanbeige\start.bat                        # 启动服务（窗口常驻，Ctrl+C 停止）
llama_cpp\nanbeige\chat.bat "你好"                   # 发提示词
llama_cpp\minicpmv\vlm.bat --image D:\pic.png        # 传图给多模态模型
llama_cpp\minicpmv\vlm.bat --video D:\clip.mp4       # 传视频
python llama_cpp\start_server.py --list              # 列出全部模型
```

每个模型目录的 `start.bat` 顶部用 `SET` 暴露全部可配置参数（上下文长度、MoE、思考等），直接改 `SET` 行改默认值，或命令行追加参数临时覆盖（命令行优先级最高）。完整参数表见 `scripts\llama_cpp\README.md` 第 3 节。

### 6.3 ComfyUI 图像/视频/音乐

```powershell
# 先启动 ComfyUI 服务
comfyui\start-comfyui.bat

# 文生图
comfyui\zimage\run.bat "锈海少女站在船头"
python comfyui\run.py image --model ernie --prompt "信息图海报"

# 视频（含原生音效）
comfyui\minimax-h3\run_t2v.bat "镜头缓慢推近"
python comfyui\run.py video --first-frame start.png --prompt "推近" --length 73

# 音乐
comfyui\acestep\run.bat "ambient, cinematic, piano" --duration 20
python comfyui\run.py music --tags "pop, female vocal" --lyrics "……"
```

工作流里的模型名只需写文件名，`comfy_client.resolve_model_names()` 会通过 `/object_info` 自动校正为当前可用的相对路径。

### 6.4 other（TTS / 音乐质检 / ASR）

```powershell
cd D:\models\scripts\other

# 语音合成
python tts_moss.py --text "你好，这是本地语音合成测试。"
python tts_moss.py --text "记住这个颜色。" --ref-audio ref.wav   # 克隆音色

# 音乐质检
python music_qc.py song.wav

# 语音转写 + 说话人分离
python asr_diarize.py dialogue.wav
python asr_diarize.py dialogue.wav --speakers 3
python asr_diarize.py dialogue.wav --align --split-gap 0.5        # 字级时间戳
```

---

## 7. 关键技术决策

### 7.1 MoE 专家层卸载
Qwen3.6-35B-A3B（19.7 GB）通过 `--n-cpu-moe 99` 把专家权重留在内存，激活的 3B 走 GPU，8GB 显存可跑。显存宽裕可降低该值提速。

### 7.2 思考的两层控制
- **服务端**：`start_server.py --think on --think-format deepseek`（模型默认要不要思考）；`deepseek-r1`、`qwen36` 默认开启。
- **请求侧**：`chat.py --think on|off` / `vlm_test.py --think on|off`（本次对话要不要思考，走 `chat_template_kwargs`）。

### 7.3 ASR + 说话人分离链路
silero-vad 分段 → Qwen3-ASR-0.6B 逐段转写 → campplus 提声纹 → KMeans 聚类分配说话人 → 可选 Qwen3-ForcedAligner 做字级对齐。
- 绕过 FunASR 1.4.16 未向 Qwen3-ASR 传递 forced_aligner 的缺陷，直接用 `qwen_asr` 包加载。
- silero-vad 对 ≥0.3s 静音敏感，对白场景 VAD 段即说话人单元。

### 7.4 音乐质检闭环
ACE-Step 1.5 生成 → MOSS-Music-8B 检测（调性/配器/情绪/时长）。MOSS-Music 对 BPM/拍号判断不准，质检以调性/配器/情绪/时长为主判据。

### 7.5 显存互斥
ComfyUI（≈8GB 独占）与 MOSS-Music（≈6GB 独占）不可同时运行，切换前必须先停对方进程释放显存。

---

## 8. 已放弃的技术路线

| 路线 | 放弃原因 | 替代方案 |
|------|----------|----------|
| Wan2.2 全链路 | 清理模型权重与中间产物 | MiniMax H3 int8 作为唯一视频模型 |
| MiniMax H3 w6a8 | 清理，仅保留 int8 版本 | — |
| SenseNova-U1 | 放弃全部技术路线 | — |
| ACE-Step GGUF 轻量链路 | 无法接入 ComfyUI | ACE-Step 1.5 safetensors 版（ComfyUI 0.37 原生支持） |
| LFM2-24B-A2B | 与 LFM2.5-8B-A1B 定位重叠且更重 | LFM2.5-8B-A1B |
| pyannote | 兼容问题难以解决 | sherpa-onnx（亦有缺陷）→ 最终用 FunASR + campplus + Qwen3-ASR |
| faster-whisper | 清理 | Qwen3-ASR-0.6B |

---

## 9. 实测状态（2026-10-14）

| 链路 | 状态 |
|------|------|
| llama.cpp nanbeige 启动 + chat | 通过（思考 on/off 均测） |
| llama.cpp minicpmv 启动 + vlm 传图 | 通过（成功读出图片文字） |
| ComfyUI zimage 文生图 | 通过（1088×608，8 步，911KB PNG） |
| ComfyUI acestep 音乐生成 | 通过（20s，flac） |
| ComfyUI minimax-h3 文生视频 | 通过（5 帧，含音轨 mp4） |
| ComfyUI minimax-h3 图生视频 | 通过（上传 PNG 后生成 mp4） |
| ComfyUI ernie / anima | 模型名校验通过（链路同 zimage） |
| other tts / music_qc / asr_diarize | `py_compile` + `--help` 通过（逻辑移植自已跑通版本） |

---

## 10. 迁移到另一台电脑

1. 把 `D:\models\scripts\` 下的 `llama_cpp/`、`comfyui/`、`other/`、`config.py` 拷到目标机对应位置（自包含，无本机绝对路径硬编码）。
2. 目标机按同样布局放好 `models\`、`llama.cpp\`、`ComfyUI\`；布局不同则设置 `config.py` 中的环境变量。
3. 确认目标机已编译 llama.cpp（存在 `llama-server.exe`）并已启动 ComfyUI。
4. `other/` 需装有依赖的 Python 环境（torch / transformers / funasr / bitsandbytes / qwen_asr 等）。
5. 直接运行各模型目录里的 .bat。

---

## 11. 注意事项

- **显存互斥**：ComfyUI 与 MOSS-Music-8B 都需独占 ~6-8GB 显存，切换前先停对方。
- llama.cpp 服务默认 `0.0.0.0:8080`；ComfyUI 默认 `8188`。两者可同时运行（显存够时）。
- PowerShell 脚本必须带 UTF-8 BOM，否则中文路径会被错误解码。
- Windows 批处理脚本避免使用 UTF-8 中文注释，防止 cmd.exe 解码异常。
- pip 已全局配置清华源，所有 `pip install` 自动走清华镜像。
