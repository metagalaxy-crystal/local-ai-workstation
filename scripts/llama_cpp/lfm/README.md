# LFM2.5-8B-A1B（注册表 key：`lfm`）

8B MoE（每 token 只激活 1B 参数），速度接近 3B 但质量更好。适合通用对话、分镜路由等日常任务。非思考模型。

## 模型文件

| 项 | 路径（相对 `MODEL_ROOT`） | 体积 |
| --- | --- | --- |
| 主模型 | `text/LFM2.5-8B-A1B/LFM2.5-8B-A1B-Q4_K_M.gguf` | 4.8 GB |
| mmproj | 无（纯文本，不能传图） | — |

## 双击运行（Windows）

1. 双击 **`start.bat`** 启动服务（窗口常驻，Ctrl+C 停止）
2. 另开窗口双击 **`chat.bat`**，输入问题

`start.bat` 顶部的 `SET` 行是可编辑的默认值，直接改这些行即改默认启动参数；也可在命令行追加参数临时覆盖（命令行优先级最高）。完整参数表见上级目录 README 第 3 节。

## 命令行

本模型 `start.bat` 预配置的默认值：`CTX=16384`、`NGL=99`、`THREADS=6`，其余留空走注册表。

```powershell
start.bat --port 8081 --ctx 8192                     # 覆盖启动参数
.\chat.bat "给锈海少女写 3 个镜头" --stream
..\chat.py -p "写一段 Python 快排" --temp 0.7 --repeat-penalty 1.1
```

## 预置参数（`..\models.json`）

- 服务端：`-ngl 99 -c 16384 -t 6 -fa on`
- 采样：temperature 0.7 / top_p 0.9 / top_k 40

## 依赖

本目录的 .bat 转调上级引擎 `..\start_server.py`、`..\chat.py` 与 `..\..\config.py`。单独拷贝本目录时需连同这些文件一起带走。
