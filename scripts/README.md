# 本地模型运行样例

本目录把 `d:\models` 下**所有模型的运行方式**整理成可复制、可迁移的样例，按运行引擎分成三部分；**每部分内部再按模型分目录**——每个模型目录都自带该模型的双击入口（.bat）、工作流与说明，换一台装好 llama.cpp / ComfyUI 的电脑可直接使用：

| 目录 | 覆盖的模型 | 运行引擎 |
| --- | --- | --- |
| `llama_cpp/` | `models\text\` 下的全部 GGUF（含 mmproj 多模态），7 个模型子目录 | llama.cpp `llama-server`（OpenAI 兼容 HTTP） |
| `comfyui/` | Z-Image / ERNIE-Image / Anima / ACE-Step 1.5 / MiniMax H3，5 个模型子目录 | ComfyUI（`/prompt` 图任务队列 API） |
| `other/` | MOSS-TTS、MOSS-Music-8B、Qwen3-ASR + campplus + ForcedAligner | 各模型自己的 Python 推理栈（不经 llama.cpp / ComfyUI） |
| `blender_mcp/` | Blender Lab 官方 MCP（26 个工具）+ 火花猫建模样例 | Blender 5.1 扩展 + `blender-mcp` MCP 服务端（TCP 9876） |

**所有样例的产物统一输出到 `d:\models\output\`**，按 `引擎/案例/` 分目录，原始模型目录与 ComfyUI 内部目录都不会被污染。

```text
d:\models\output\
├── llama_cpp\chat\      # 文本对话产物（.md 可读 + .json 原始）
├── llama_cpp\vlm\       # 图片理解产物
├── comfyui\image_zimage\    # 文生图
├── comfyui\image_ernie\
├── comfyui\image_anima\
├── comfyui\music_acestep\   # 音乐
├── comfyui\video_h3\        # 视频（t2v / i2v 共用）
└── other\tts\ / music\ / asr\
```

---

## 一、公共配置层（迁移时唯一需要关心的文件）

`config.py` 集中解析所有路径，**每一项都可用环境变量覆盖**：

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `MODEL_ROOT` | `d:\models\models` | 模型根目录（GGUF / safetensors 都在这） |
| `LLAMA_DIR` | `d:\models\llama.cpp` | llama.cpp 源码与编译产物目录 |
| `COMFY_DIR` | `d:\models\ComfyUI` | ComfyUI 目录 |
| `OUTPUT_ROOT` | `d:\models\output` | 所有样例的产物输出根目录 |
| `COMFY_HOST` | `http://127.0.0.1:8188` | ComfyUI 服务地址 |
| `LLAMA_SERVER` | `<LLAMA_DIR>\build\bin\Release\llama-server.exe` | llama-server 可执行文件 |
| `SAMPLE_PY` | `d:\models\.venv\Scripts\python.exe` | other/ 与 llama_cpp/ 使用的解释器 |
| `COMFY_PY` | `python` | comfyui/ 与 .bat 使用的解释器 |

## 二、迁移到另一台电脑

1. 把 `d:\models\scripts\` 下的 `llama_cpp/`、`comfyui/`、`other/`、`config.py` 拷到目标机对应位置（**这些文件自包含，无本机绝对路径硬编码**）。
2. 目标机按同样的布局放好 `models\`、`llama.cpp\`、`ComfyUI\`；若布局不同，设置上表的环境变量即可，**不用改任何代码**。
3. 确认目标机已编译 llama.cpp（存在 `llama-server.exe`）并已启动 ComfyUI。
4. `other/` 需要装有依赖的 Python 环境（建议与模型同机的 venv，见 `other/README.md`）。
5. 直接跑（每个模型目录里有双击可用的 .bat，命令行等价写法如下）：

```powershell
cd d:\models\scripts

# 1) llama.cpp：进模型目录双击 start.bat / chat.bat，或命令行
llama_cpp\nanbeige\start.bat                  # 一个窗口常驻服务
llama_cpp\nanbeige\chat.bat "你好"            # 另一个窗口发提示词
llama_cpp\minicpmv\vlm.bat --image D:\pic.png # 传图给多模态模型
python llama_cpp\start_server.py --list       # 引擎直调，列出全部模型

# 2) ComfyUI（先双击 comfyui\start-comfyui.bat 启动服务）
comfyui\zimage\run.bat "锈海少女"
comfyui\minimax-h3\run_t2v.bat "镜头推近" --length 73
comfyui\acestep\run.bat "ambient, piano" --duration 20

# 3) other
python other\tts_moss.py --text "你好"
python other\music_qc.py song.wav
python other\asr_diarize.py dialogue.wav --align
```

模型目录只做转调，引擎脚本（`llama_cpp\start_server.py`、`comfyui\run_image.py` 等）在引擎根目录共用；**只拷贝单个模型目录时**，各模型 README 末尾写明了需要连带带走的引擎文件。

## 三、为什么 `comfyui/` 样例不担心模型目录变动

这是本套样例最关键的设计。ComfyUI 解析模型名走的是 `folder_paths.get_full_path()`，它**只按「注册根 + 你写的名字」精确拼接**，不做 basename 递归回退。而 `extra_model_paths.yaml` 里 `diffusion_models / text_encoders / vae` 三个类别分别映射到 `video/ image/ music/` 这三个子目录（`get_filename_list_` 会递归列出，名字形如 `Z-Image\vae\ae.safetensors`）。

所以：

- 模型名**必须写成相对注册根的相对路径**（如 `MiniMax-H3\vae\minimax_h3_video_vae_fp16.safetensors`），只写文件名会报找不到。
- 但目录一旦重组，写死的相对路径就会失效。`comfy_client.resolve_model_names()` 通过 `/object_info` 拉取**当前实际可用的模型清单**，用 basename 匹配后把工作流里的名字改写成正确的相对路径，因此样例里的工作流可以直接写「文件名」，由脚本自动校正。

工作流里的 `_meta` 键只是样例的元数据（不会被提交给 ComfyUI；`comfy_client.submit()` 会剔除所有以 `_` 开头的键，且值一律会被过滤/剔除）。

## 四、实测状态（2026-10-14 本机实测）

| 样例 | 语法/接口 | 真实运行 |
| --- | --- | --- |
| `llama_cpp` nanbeige 启动 + `chat.py` 发提示词 | 通过 | **通过**（思考 on/off 均测） |
| `llama_cpp` minicpmv 启动 + `vlm_test.py` 传图 | 通过 | **通过**（成功读出图片文字内容） |
| `comfyui` zimage 文生图 | 通过 | **通过**（1088x608，8 步，产物 911 KB PNG） |
| `comfyui` acestep 音乐生成 | 通过 | **通过**（20s，产物 flac） |
| `comfyui` minimax_h3 文生视频 | 通过 | **通过**（5 帧，含音轨 mp4） |
| `comfyui` minimax_h3 图生视频（含图片上传） | 通过 | **通过**（上传 PNG 后生成 mp4） |
| `comfyui` ernie / anima 文生图 | 模型名校验通过 | 未逐条重跑（链路同 zimage） |
| `other` tts / music_qc / asr_diarize | `py_compile` + `--help` 通过 | 未在本机重跑（逻辑移植自已跑通的项目版） |

其余所有工作流都通过了 `run.py names <wf.json>` 的在线模型名校验（6/6 全部能解析到实际文件）。

## 五、注意事项

- **显存互斥**：ComfyUI 与 `other/music_qc.py`（MOSS-Music-8B）都需要独占 ~6-8GB 显存，**切换前先停对方进程**。
- llama.cpp 服务默认监听 `0.0.0.0:8080`；ComfyUI 默认 `8188`。两者可同时运行（显存够的话）。
- 服务端思考开关：`llama-server` 侧用 `-rea`/`--reasoning-format`，请求侧用 `chat_template_kwargs`（`chat.py --think` / `vlm_test.py --think`）。
