# Nanbeige4.2-3B（注册表 key：`nanbeige`）

3B 小模型，**速度最快**，开 32K 上下文。适合分镜草稿、批量改写、长文摘要等大量重复生成场景。思考模式可选（注册表默认不开服务端思考，请求侧可 `--think on`）。

## 模型文件

| 项 | 路径（相对 `MODEL_ROOT`） | 体积 |
| --- | --- | --- |
| 主模型 | `text/Nanbeige4.2-3B/Nanbeige4.2-3B-Q4_K_M.gguf` | 2.4 GB |
| mmproj | 无（纯文本，不能传图） | — |

## 双击运行（Windows）

1. 双击 **`start.bat`** 启动服务（窗口常驻，Ctrl+C 停止；默认 `0.0.0.0:8080`）
2. 另开窗口双击 **`chat.bat`**，按 `Prompt:` 提示输入问题即可

`start.bat` 顶部的 `SET` 行是可编辑的默认值，直接改这些行即改默认启动参数；也可在命令行追加参数临时覆盖（命令行优先级最高）。完整参数表见上级目录 README 第 3 节。

## 命令行

本模型 `start.bat` 预配置的默认值：`CTX=32768`、`NGL=99`、`THREADS=6`、`KV_TYPE=q4_0`，其余留空走注册表。

```powershell
# 启动（参数可覆盖，见上级目录 README 的参数表）
..\start_server.py nanbeige                          # 用注册表推荐参数
start.bat --port 8081 --ctx 16384                    # .bat 追加覆盖参数

# 对话
.\chat.bat "用三句话介绍蒸汽朋克" --stream
..\chat.py -p "广州是哪个省的省会？" --think off
..\chat.py --prompt-file prompt.txt --system "你是分镜师" --temp 0.8
```

## 预置参数（`..\models.json`）

- 服务端：`-ngl 99 -c 32768 -t 6 -fa on -ctk q4_0 -ctv q4_0`
- 采样：temperature 0.7 / top_p 0.9 / top_k 40

## 实测（2026-10-14）

服务启动正常；`chat` 默认会输出思考段，`--think off` 可完全关闭（2.3s → 0.6s）；8GB 显存可全部卸载到 GPU。

## 依赖

本目录的 .bat 转调上级引擎 `..\start_server.py`、`..\chat.py` 与 `..\..\config.py`。单独拷贝本目录时需连同这些文件一起带走。
