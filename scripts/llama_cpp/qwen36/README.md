# Qwen3.6-35B-A3B（注册表 key：`qwen36`）

35B MoE（每 token 激活约 3B）+ mmproj 多模态，是本机**质量最高**的语言/图片/视频理解模型，用于质检、评测、图片理解、视频理解、要求最高质量的生成。注册表默认把专家权重留在内存（`--n-cpu-moe 99`），8GB 显存也能跑。支持思考。

## 模型文件

| 项 | 路径（相对 `MODEL_ROOT`） | 体积 |
| --- | --- | --- |
| 主模型 | `text/Qwen3.6-35B-A3B/Qwen3.6-35B-A3B-Q4_K_M.gguf` | 19.7 GB |
| mmproj | `text/Qwen3.6-35B-A3B/mmproj-Qwen3.6-35B-A3B-BF16.gguf` | 0.84 GB |

## 双击运行（Windows）

1. 双击 **`start.bat`** 启动服务（已加载 mmproj；显存宽裕可改 `--n-cpu-moe 0` 提速）
2. 文本对话：双击 **`chat.bat`**（默认 `--think on`）
3. 图片理解：双击 **`vlm.bat`**（不带参数用 llama.cpp 自带测试图）

`start.bat` 顶部的 `SET` 行是可编辑的默认值，直接改这些行即改默认启动参数；也可在命令行追加参数临时覆盖（命令行优先级最高）。完整参数表见上级目录 README 第 3 节。

## 命令行

本模型 `start.bat` 预配置的默认值：`CTX=16384`、`NGL=99`、`THREADS=6`、`N_CPU_MOE=99`、`THINK=on`、`THINK_FORMAT=deepseek`，其余留空走注册表。

```powershell
# 显存/内存权衡：专家留内存的层数，越小越快越吃显存
start.bat --n-cpu-moe 40 --ctx 8192

# 传图 / 传视频（--image 可多次做多图对比，--video 传视频，两者可混用）
.\vlm.bat --image D:\a.png -p "描述这张图"
.\vlm.bat --video D:\clip.mp4 -p "用三句话概括这个视频"
..\vlm_test.py --model qwen36 --image a.jpg --image b.jpg -p "对比两张图"
.\vlm.bat --think off -p "图里有哪些文字？" --max-tokens 512
```

## 预置参数（`..\models.json`）

- 服务端：`-ngl 99 --cpu-moe --load-mode none -c 16384 -t 24 -fa on --jinja -rea on --reasoning-format deepseek`
- 采样：temperature 0.7 / top_p 0.8 / top_k 20

## 备注

2026-10-19 实测调优（RTX 5060 8GB / 32GB 内存）：关键三元组 `--cpu-moe --load-mode none -t 24` 把生成速度从 7.3 tok/s 提到 **~39 tok/s**（专家权重全留内存且常驻，避免 mmap 页面被挤出回读 SSD；半卸载 `--n-cpu-moe 24` 反而掉到 10 tok/s，不要用）。19.7 GB 模型加载较慢（分钟级）。旧配置（-ngl 24）测试结果存档于 `d:\models\docs\bench_results\qwen35b_旧配置ngl24\`。

## 依赖

本目录的 .bat 转调上级引擎 `..\start_server.py`、`..\chat.py`、`..\vlm_test.py` 与 `..\..\config.py`。单独拷贝本目录时需连同这些文件一起带走。
