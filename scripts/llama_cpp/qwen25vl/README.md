# Qwen2.5-VL-7B-Instruct（注册表 key：`qwen25vl`）

7B 多模态备选模型。对图表、表格、复杂版面的理解比 MiniCPM-V 更细；代价是体积更大、速度更慢。非思考模型。

## 模型文件

| 项 | 路径（相对 `MODEL_ROOT`） | 体积 |
| --- | --- | --- |
| 主模型 | `text/Qwen2.5-VL-7B/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf` | 4.4 GB |
| mmproj | `text/Qwen2.5-VL-7B/mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf` | 0.79 GB |

## 双击运行（Windows）

1. 双击 **`start.bat`** 启动服务（自动带 `-mm` 加载投影）
2. 双击 **`vlm.bat`**：不带参数即用 llama.cpp 自带测试图提问
3. 纯文本对话用 **`chat.bat`**

`start.bat` 顶部的 `SET` 行是可编辑的默认值，直接改这些行即改默认启动参数；也可在命令行追加参数临时覆盖（命令行优先级最高）。完整参数表见上级目录 README 第 3 节。

## 命令行

本模型 `start.bat` 预配置的默认值：`CTX=8192`、`NGL=99`、`THREADS=6`，其余留空走注册表。

```powershell
start.bat --ctx 16384
.\vlm.bat --image D:\chart.png -p "读出图表里的横纵轴和所有数据点"
..\vlm_test.py --model qwen25vl --image a.jpg --image b.jpg -p "对比两张表格"
```

## 预置参数（`..\models.json`）

- 服务端：`-ngl 99 -c 8192 -t 6 -fa on --mmproj-offload`
- 采样：temperature 0.7 / top_p 0.8 / top_k 20

## 选型建议

日常图生文先用 `minicpmv`（快 10 倍以上）；图表/版面/票据类细粒度识别再换本模型。

## 依赖

本目录的 .bat 转调上级引擎 `..\start_server.py`、`..\chat.py`、`..\vlm_test.py` 与 `..\..\config.py`。单独拷贝本目录时需连同这些文件一起带走。
