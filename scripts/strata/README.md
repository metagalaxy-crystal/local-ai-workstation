# Strata 云端模型调用方法

云端 Strata 模型调用样例（按 scripts 目录"引擎+模型"两级约定存放）。调用封装从同目录 `bench\bench_universal.py` 提炼而来，纯标准库实现，无第三方依赖。

## 调用要点

| 项 | 值 |
|---|---|
| 协议 | OpenAI 兼容 `/v1/chat/completions`（vLLM 服务） |
| 端点 | `http://10.203.239.162:8082/v1/chat/completions` |
| 鉴权 | `Authorization: Bearer <STRATA_API_KEY>`（从环境变量读取） |
| 模型名 | 固定传 `"bench"`（服务端注册名，改名会 404） |
| 推理强度 | `"reasoning_effort"`: `low`（默认，最快）/ `medium` / `high` |
| 超时 | 建议 1800s（high 档长输出时较慢） |

## 文件清单

| 文件 | 说明 |
|---|---|
| `strata_client.py` | 调用封装：`chat()` 非流式、`chat_stream()` 流式、`image_content()` 多模态构造 |
| `example_chat.py` | 对话示例：单轮 / 多轮上下文累积 / 流式输出 |
| `example_vision.py` | 多模态示例：本地图片 base64 上传 + 图片提问 |
| `run_chat.bat` | 双击运行对话示例 |
| `run_vision.bat` | 双击运行多模态示例 |
| `bench\` | 基准测试脚本：bench_universal / bench_coding / bench_reasoning / rejudge_reasoning，结果写入 `d:\models\docs\bench_results\` |

## 快速开始

```python
from strata_client import chat, chat_stream, image_content

# 普通对话
text, usage, dt = chat([{"role": "user", "content": "你好"}])

# 多模态：本地图片直接传路径
content = image_content("描述这张图", r"D:\path\to\img.png")
text, usage, dt = chat([{"role": "user", "content": content}])

# 流式
for piece in chat_stream([{"role": "user", "content": "讲个故事"}]):
    print(piece, end="", flush=True)
```

## 多模态消息格式

与 OpenAI Vision 规范一致，`content` 用数组，图片转 base64 data URL：

```json
{"role": "user", "content": [
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,<b64>"}},
  {"type": "text", "text": "描述这张图片"}
]}
```

支持 png / jpg / jpeg / webp / gif（按后缀自动识别 mime）。

## 与本地模型的差异

- 本地 llama-server 无需 key、模型名传实际模型名；Strata 需 Bearer key 且模型名固定 `bench`
- 本地思考型模型用 `chat_template_kwargs.enable_thinking:false` 关思维链；Strata 用 `reasoning_effort` 分档控制
- 其余 payload 字段（temperature / max_tokens / messages 结构）完全一致，脚本可平移
