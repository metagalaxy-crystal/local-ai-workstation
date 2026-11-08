# Blender Lab 官方 MCP 样例（两档）

用 MCP 协议把 Blender 变成可编程建模工具。目录下有两个样例：

| 样例 | 谁写的场景代码 | 用途 |
| --- | --- | --- |
| `run_demo.py` + `spark_cat.py` | 人（固定脚本） | 验证 MCP 链路、出基准图，结果稳定可复现 |
| `agent_demo.py` + 大模型 | 本地大模型现场生成 | 演示「一句话需求 → 大模型写 bpy → 调用 MCP → 出图」 |

## 链路

```text
用户需求
  ├─▶ llama-server（OpenAI 兼容 /v1）── tool_call ──┐
  └──────────────────────────────▶ run_demo 客户端 ──MCP/stdio──▶ blender-mcp
                                                              │ TCP 127.0.0.1:9876
                                                              ▼
                                                          Blender 插件
```

| 组件 | 本机位置 |
| --- | --- |
| MCP 服务端 | `d:\models\tools\mcp-servers\blender_mcp_lab\mcp\.venv\Scripts\blender-mcp.exe` |
| Blender 插件 | 已装为扩展 `bl_ext.user_default.mcp`（Blender 5.1） |
| 本地大模型 | `d:\models\scripts\llama_cpp\qwen36\start.bat`（:8080，Qwen3.6-35B-A3B） |

## 文件

| 文件 | 作用 |
| --- | --- |
| `spark_cat.py` | 固定版场景脚本：猫体、70 颗螺旋火花 + 26 颗尾迹火花、Fog Glow 合成 |
| `run_demo.py` | 最小 stdio MCP 客户端（仅标准库）：起桥接 → 调用 `execute_blender_code` |
| `run_demo.bat` | 固定版双击入口 |
| `agent_demo.py` | 大模型驱动版：流式调用本地模型，跑 tool_call 循环，自动重试与截断保护 |
| `finalize_scene.py` | 收尾脚本：统一渲染参数、按包围盒自动取景、补灯、压暗背景、存工程 |
| `agent_demo.bat` | 大模型版双击入口 |

## 运行

固定版：

```powershell
python d:\models\scripts\blender_mcp\run_demo.py            # 端口未开时自动无界面拉起 Blender
python d:\models\scripts\blender_mcp\run_demo.py --no-auto-start
```

大模型版（先确认 :8080 已起，`llama-server` 未起时先跑 `scripts\llama_cpp\qwen36\start.bat`）：

```powershell
python d:\models\scripts\blender_mcp\agent_demo.py --prompt "生成一只坐在月亮上的橘猫"
python d:\models\scripts\blender_mcp\agent_demo.py --max-rounds 6 --keep-scene
```

## 产物

| 文件 | 说明 |
| --- | --- |
| `d:\models\output\blender_mcp\spark_cat.png` / `.blend` | 固定版渲染图与工程 |
| `d:\models\output\blender_mcp\llm_spark_cat.png` / `.blend` | 大模型版渲染图与工程 |
| `d:\models\output\blender_mcp\llm_spark_cat_code.py` | 大模型实际生成的 bpy 代码存档（可复现） |

## 实测记录

- 固定版：EEVEE 1280×1280、64 采样，约 1.6 s，场景 138 个物体。
- 大模型版：qwen36 关闭思考链后，单轮约 1300~1500 completion tokens；本次 4 轮
  （前 3 轮代码报错被自动回传修复，第 4 轮成功），生成代码约 110 行，收尾渲染 1.7 s。
- 大模型版自动重试策略：工具 traceback 原样回传；`finish_reason=length` 或工具参数
  JSON 解析失败时判定为「输出被截断」，不执行坏代码，提示模型压缩到 80 行内重来。

## 关键实现点（踩坑记录）

- Blender 5.x 合成器不再有 `scene.node_tree`：改用
  `bpy.data.node_groups.new(..., "CompositorNodeTree")` + `scene.compositing_node_group`
  + `NodeGroupOutput`。只置 `use_nodes=True` 而不接输出节点，渲染结果会**全黑**。
- 5.x 的 `CompositorNodeGlare` 已资产化，参数改为输入插槽
  （`inputs["Type"]="Fog Glow"`、`Quality`、`Threshold`、`Size`）。
- 发光火花要设 `visible_shadow = False`，否则会在猫身和地面留下黑斑。
- `render_viewport_to_path` 不会写到传入路径，而是写到 Blender 的
  `tempdir/blender_mcp/<文件名>`，必须在返回的 `filepath` 上再做一次拷贝。
- 大模型经常忘建相机 / 把眼睛埋进头里：收尾脚本按网格包围盒自动取景，
  无灯时补三点光；提示词里给了具体坐标比例可显著提升成功率。
- 工具参数在 `max_tokens` 处被截断时，llama-server 会在下一轮直接返回 500
  （`Failed to parse tool call arguments as JSON`），必须在客户端做截断检测。
- 插件启动需要 Blender 偏好里的「Allow Online Access」；无界面启动需带 `--online-mode`。
