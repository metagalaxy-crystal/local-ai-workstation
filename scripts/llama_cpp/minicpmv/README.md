# MiniCPM-V-4.6（注册表 key：`minicpmv`）

0.5B 主模型 + 0.7B mmproj 投影，**体积小、加载快**，是看图说话 / 图片描述 / OCR / 视频理解的主力。支持思考模式（默认不开）。

**能力**：图片理解（含 OCR）+ 视频理解（短视频内容描述）。

## 模型文件

| 项 | 路径（相对 `MODEL_ROOT`） | 体积 |
| --- | --- | --- |
| 主模型 | `text/MiniCPM-V-4_6/MiniCPM-V-4.6-Q4_K_M.gguf` | 0.49 GB |
| mmproj | `text/MiniCPM-V-4_6/mmproj-MiniCPM-V-4.6-Q8_0.gguf` | 0.68 GB |

## 双击运行（Windows）

1. 双击 **`start.bat`** 启动服务（自动带 `-mm` 加载投影）
2. 双击 **`vlm.bat`**：不带参数即用 llama.cpp 自带测试图提问；也可在命令行传 `--image`
3. 纯文本对话用 **`chat.bat`**

`start.bat` 顶部的 `SET` 行是可编辑的默认值，直接改这些行即改默认启动参数；也可在命令行追加参数临时覆盖（命令行优先级最高）。完整参数表见上级目录 README 第 3 节。

## 命令行

本模型 `start.bat` 预配置的默认值：`CTX=8192`、`NGL=99`、`THREADS=6`，其余留空走注册表。

```powershell
.\vlm.bat --image D:\pic.png -p "描述这张图"
.\vlm.bat --image a.png --image b.png -p "对比两张图"
.\vlm.bat --video D:\clip.mp4 -p "用三句话概括这个视频的内容"
.\vlm.bat --video a.mp4 --image b.png -p "视频和图片有什么关系"
.\vlm.bat --think off -p "图里有哪些文字？" --max-tokens 300
..\vlm_test.py --model minicpmv --image D:\pic.png --prompt-file q.txt
```

媒体类型按后缀自动判断（`.jpg/.png/.jpeg/.webp/.gif` 为图片，其余按视频处理），`--image` 与 `--video` 可混用。

## 预置参数（`..\models.json`）

- 服务端：`-ngl 99 -c 8192 -t 6 -fa on --mmproj-offload`
- 采样：temperature 0.7 / top_p 0.8 / top_k 20

## 实测（2026-10-14）

成功识别图片上的报纸标题与正文（读出了 "MEN WALK ON MOON" 等文字）；`--think off` 得到干净的中文分点描述；8GB 显存可完整卸载。

## 依赖

本目录的 .bat 转调上级引擎 `..\start_server.py`、`..\chat.py`、`..\vlm_test.py` 与 `..\..\config.py`。单独拷贝本目录时需连同这些文件一起带走。
