# llama.cpp 运行样例（文本 / 多模态语言模型）

用 `llama-server` 常驻一个 OpenAI 兼容的 HTTP 服务，再用客户端发提示词。**每个模型一个同名目录**，里面放该模型的双击入口和说明；通用引擎脚本放在本层共用。

```
llama_cpp\
├── models.json            # 模型注册表（路径 + 推荐启动/采样参数），引擎共用
├── start_server.py        # 引擎：启动服务，可覆盖注册表的每一个参数
├── chat.py                # 引擎：发文本提示词（思考开关 / 流式）
├── vlm_test.py            # 引擎：给带 mmproj 的模型传图片提问
├── run.py                 # 引擎级命令行入口：list / start / chat / vlm
├── bench.py  smoke_test.py
│
├── nanbeige\              # Nanbeige4.2-3B（最快，分镜/改写/摘要）
│   ├── start.bat  chat.bat  README.md
├── lfm\                   # LFM2.5-8B-A1B（MoE 激活 1B，速度王 + agent）
│   ├── start.bat  chat.bat  README.md
├── qwen36\                # Qwen3.6-35B-A3B（最高质量 + 图片理解，默认开思考）
│   ├── start.bat  chat.bat  vlm.bat  README.md
├── minicpmv\              # MiniCPM-V-4.6（看图/OCR 主力，体积小）
│   ├── start.bat  chat.bat  vlm.bat  README.md
└── qwen25vl\              # Qwen2.5-VL-7B（图表/版面理解备选）
    ├── start.bat  chat.bat  vlm.bat  README.md
```

## 1. 用法（以模型为单位）

**双击派**：进模型目录 → 双击 `start.bat`（服务常驻，Ctrl+C 停止）→ 另一窗口双击 `chat.bat`（无参数时交互输入）；带 mmproj 的模型用 `vlm.bat` 传图。

**命令行派**：

```powershell
# 直接用引擎（模型 key 见 models.json）
python start_server.py --list
python start_server.py nanbeige
python chat.py -p "用一句话说明你是什么模型"
python vlm_test.py --model minicpmv --image D:\pic.png -p "描述这张图"

# 或用模型目录里的 .bat（等价，且预置了模型 key / 思考默认值）
.\nanbeige\start.bat --port 8081
.\lfm\chat.bat "用一句话说明你是什么模型" --stream
.\minicpmv\vlm.bat --image D:\pic.png
```

`.bat` 默认用 PATH 上的 `python`；要指定解释器设环境变量 `SAMPLE_PY`。

## 2. 模型一览

| 目录 / key | 模型 | 体积 | 思考 | mmproj | 擅长 |
| --- | --- | --- | --- | --- | --- |
| `nanbeige` | Nanbeige4.2-3B | 2.4 GB | 可选 | — | 分镜草稿、批量改写、长文摘要、轻量 agent |
| `lfm` | LFM2.5-8B-A1B | 4.8 GB | 无 | — | 速度王 + agent（MoE 只激活 1B，短输出） |
| `qwen36` | Qwen3.6-35B-A3B | 19.7 GB | 默认开 | 0.84 GB | 质检、评测、图片+视频理解、最高质量生成 |
| `minicpmv` | MiniCPM-V-4.6 | 0.5 GB | 可选 | 0.68 GB | 看图说话、OCR、视频理解（主力，体积小） |
| `qwen25vl` | Qwen2.5-VL-7B-Instruct | 4.4 GB | 无 | 0.79 GB | 图表 / 版面理解（图片为主） |

带 mmproj 的三个（`qwen36` / `minicpmv` / `qwen25vl`）可以传图片；`qwen36` 与 `minicpmv` 还支持传视频（短视频内容理解），`vlm.bat --video D:\clip.mp4`。

## 3. 启动参数（全参数可覆盖）

**覆盖优先级：命令行 > `models.json` 推荐值 > llama.cpp 默认值。**

| 参数 | 作用 | llama.cpp 原生参数 |
| --- | --- | --- |
| `--host` / `--port` | 监听地址，默认 `0.0.0.0:8080` | `--host` / `--port` |
| `--alias` | 对外模型名（`/v1/models` 里显示） | `--alias` |
| `--ctx` | 上下文长度 | `-c` |
| `--ngl` | 卸载到 GPU 的层数（99=全部） | `-ngl` |
| `--threads` | CPU 线程数 | `-t` |
| `--kv-type` | KV cache 量化（同时设 K/V），如 q8_0/q4_0 | `-ctk` / `-ctv` |
| `--n-cpu-moe` | MoE 专家权重留在内存的层数 | `--n-cpu-moe` |
| `--think` | **思考开关** on/off/auto | `-rea` |
| `--think-effort` | 思考强度 default/low/medium/high | `--reasoning-effort` |
| `--think-budget` | 思考 token 预算（-1 不限、0 立即结束） | `--reasoning-budget` |
| `--think-format` | `deepseek` 把思考放进 `reasoning_content` | `--reasoning-format` |
| `--no-jinja` | 关掉 jinja 模板引擎 | `--no-jinja` |
| `--extra` | 追加任意原生参数（可多次） | 原样透传 |
| `--dry-run` | 只打印命令，不启动 | — |

注册表里也可以直接写其他原生参数：`qwen36` 用了 `--cpu-moe`。

## 4. 思考的两层控制

- **服务端**：`start_server.py --think on --think-format deepseek`（模型默认要不要思考、思考怎么塞进响应）；`qwen36` 的注册表与 .bat 已默认开启。
- **请求侧**：`chat.py --think on|off` / `vlm_test.py --think on|off`（这一次对话要不要思考，走 `chat_template_kwargs`）。

## 5. 产物

- 对话：`d:\models\output\llama_cpp\chat\<tag>.md`（含思考过程与正式输出）+ `.json`（原始响应）
- 图片：`d:\models\output\llama_cpp\vlm\<model>_<tag>.md`

## 6. 实测结论（2026-10-20，五轮横评：中文卷 / 英文卷 / 推理卷 / 编程卷 / 工具调用）

- **Qwen3.6-35B** 全能旗舰：写作/摘要/推理（10/10）/编程（5/5）/工具调用（3/3）全第一。
- **Nanbeige-3B** 轻量档质量最稳（写作/摘要 4.5/5），工具调用 3/3。
- **LFM2.5-8B** 速度王（~222 tok/s），工具调用 3/3 最干净；长文写作思考链易泄入正文。
- 已删除（2026-10-20 方案 A''，省 23.5 GB）：LFM2-24B（被 Qwen36 全面覆盖）、Ornith-9B（编程 5/5 但草稿烧 token、其余垫底）、DeepSeek-R1-8B（思维链失控跨四轮复现，本机栈无解）。
- 已删除（2026-11-08，省 21.1 GB）：Nemotron-3-Nano-Omni-30B-A3B（推理 10/10 且最省 token、编程 5/5、工具调用 3/3 弱通过，唯一全模态；中文卷偶发英文作答）。测试结果仍保留在 `docs\bench_results\nemotron*\` 与五份测试报告。
- 详细数据见 `D:\models\docs\` 五份测试报告，原始输出在 `D:\models\docs\bench_results\`。

## 7. 注意

- 服务常驻，Ctrl+C 停止；换模型前先停上一个（显存互斥）。
- 默认端口 8080；冲突时 `--port` 指定。
- 每个模型目录的 .bat 只做转调；**单独拷贝某个模型目录时**，需连同本层的 `start_server.py`、`chat.py`、（VLM 还要）`vlm_test.py`、`models.json` 与上级 `..\config.py` 一起带走。
