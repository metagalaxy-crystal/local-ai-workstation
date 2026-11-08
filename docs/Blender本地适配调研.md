# Blender 本地 AI 适配调研

> 调研日期：2026-11-03
> 本机基线：RTX 5060 Laptop 8GB / RAM 34GB / Windows / Blender 5.1 已安装（`C:\Program Files\Blender Foundation\Blender 5.1`）

---

## 一、结论先行

| 目标 | 推荐结论 | 理由 |
|---|---|---|
| Blender 自动化主路径 | **Blender Lab 官方 MCP Server（Blender 5.1+）+ 本地 llama.cpp 模型** | 版本正好匹配（本机 5.1）、官方维护、公开文档明确用 llama.cpp 作为 LLM 客户端 |
| 备选 | **mcp-for-blender（ahujasid）** | MIT、Blender 3.0+、带 `look` 视觉回读、Poly Haven/Poly Pizza 资产库、本地/云端模型都能接 |
| 3D-Agent | **本机不适配** | 桌面 App 可用在 Windows，但推理在其云端、按 prompts 订阅（$19/$29/$89 每月），不是本地链路 |
| Claude Blender connector | **不适配本地链路** | 仅 Claude Desktop + 云端 Claude |
| 用 GUI 自动化（看像素点坐标）操作 Blender | **不推荐** | Blender 有完整 Python API，走 API 比走 GUI 精确一个量级，且视口密集小控件容易点偏 |

**一句话方案**：Blender 侧走「官方 MCP + 本地 qwen36（llama.cpp）」，视觉回读按需加装 mcp-for-blender 的 `look`。

---

## 二、四条路线对比

| 维度 | Blender Lab 官方 MCP | mcp-for-blender（ahujasid） | Claude Blender connector | 3D-Agent |
|---|---|---|---|---|
| 出品 | Blender Lab（官方） | 社区（非官方），MIT | Blender 官方 + Anthropic 连接器 | 商业团队 |
| Blender 版本 | **5.1+**（本机正好 5.1） | 3.0+ | 4.2+ / 插件要求 5.1 | 4.2+ |
| 模型来源 | 自带 MCP 客户端与模型，官方文档用 **llama.cpp** | 任意 MCP 客户端（Claude/Cursor/VS Code/Codex…） | 云端 Claude | 其云端 agent（按 prompts 计费） |
| 本地化程度 | **全本地可行** | **全本地可行** | 否 | 否 |
| 能力 | 自然语言操作 bpy API + Blender 文档检索 + 场景分析 | 9 个工具：`execute_blender_code`、`look`（多角度/渲染/线框截图）、`get_scene_info`、`generate_3d`、Poly Haven/Sketchfab/Poly Pizza 资产、状态/遥测开关 | 官方 MCP 的云端版 | 文本→模型生成、场景编辑、Roblox Studio |
| 3D 生成 | 无（靠模型写 bpy / 本地 ComfyUI） | 接 Tripo / Meshy / Hyper3D / 腾讯 Hunyuan3D（**云端 API**，Premium 可免 key） | 同官方 | 内置生成 |
| 费用 | 免费 | 免费（Premium 可选） | Claude 订阅（含免费档） | $19 / $29 / $89 每月，无免费档 |
| Windows | 可行 | 可行（`uvx mcp-for-blender setup` 官方支持） | Claude Desktop 可用 | Windows 10+ 可用 |
| 安全 | 官方警告：无沙箱、可执行任意代码，建议 VM | 有 `BLENDER_MCP_SAFE_MODE=1` 脚本校验；默认遥测仅为匿名计数 | 云端 | 云端 |

补充：
- 官方 MCP 的安装是三件套：Blender 扩展（拖拽装两次：先加 Blender Lab 仓库、再装插件）+ LLM 客户端 + MCP Server 源码（llama.cpp 不支持 `.mcpb` 包，需从源码装）。
- `mcp-for-blender` 的 socket server **无鉴权无加密**（默认 9876），只能绑 localhost；`execute_blender_code` 可执行任意 Python，用前先存盘。
- 另有学术方案 EZBlender（Plan-and-ReAct 并行化 Blender agent），目前只见到论文，未找到可用的开源发布，不纳入落地方案。

---

## 三、本机适配度评估

本机条件：8GB 显存（笔记本 5060，需留 ~0.5–1GB 给显示输出）、34GB 内存、Blender 5.1 已装、无 Blender 环境变量。

| 路线 | 适配度 | 说明 |
|---|---|---|
| Blender Lab 官方 MCP + 本地 qwen36 | **高（首选）** | 版本天然匹配 5.1；MCP Server 是普通 Python 进程，不吃显存；qwen36 用 `--cpu-moe --load-mode none` 约 39 tok/s，专家层在 34GB 内存里，显存只留 ~2–3GB 给 KV/attention |
| 同上 + qwen36 视觉 / qwen25vl（视觉） | **中高** | 需要看 `look` 截图/渲染回读时切 qwen36（BF16 mmproj，视觉精细但 27s/张）或 qwen25vl（4.8s/张更快，但原生工具调用有缺陷），建议只在"验收/看图"阶段短暂切换 |
| mcp-for-blender + 本地模型 | **高（备选）** | 资产库和视觉回读是官方 MCP 没有的；`generate_3d` 走云端 API，本地化时须关掉，改用本地 ComfyUI Hunyuan3D |
| mcp-for-blender + qwen25vl | **中** | 视觉能用，但 qwen25vl 原生工具调用有缺陷，需 JSON 模式降级，多步 loop 容易退化 |
| 3D-Agent | **低** | 能用但把活交给云端并按 prompt 付费，违背"本地链路"目标 |
| Claude connector | **低** | 模型不在本地 |

**显存/服务调度规则**（沿用现有约定）：
- Blender 渲染（EEVEE/Cycles）独占 GPU 时，先停 ComfyUI（:8188）与 MOSS；文本 LLM 因 `--cpu-moe` 主要占内存，可并存但会抢几 GB 显存。
- 工具超时：文生图 15min / 视频 60min / 音乐 20min 的既有阈值不变。

---

## 四、推荐落地配置（两阶段）

### 阶段 1：Blender 5.1 + 官方 MCP + qwen36（当天可跑）

1. **装扩展**：下载官方 `mcp-1.0.3.zip`，拖入 Blender 两次（第一次加 Blender Lab 仓库，第二次装插件），或 `Install from Disk`。
2. **装 MCP Server**：按官方 Setup wiki 从 `projects.blender.org/lab/blender_mcp` 源码安装（llama.cpp 不支持 `.mcpb`），建议 `uv` 虚拟环境隔离。
3. **起本地模型**（沿用已固化脚本）：
   ```powershell
   d:\models\scripts\llama_cpp\qwen36\start.bat
   ```
   确认 `http://127.0.0.1:8080` 的 `/props` 可访问。
4. **注册 MCP**：在 llama.cpp WebUI → MCP Server Settings 里新增 stdio 条目，命令指向刚装的 server 入口，工作目录用绝对路径（Craft/自动化层对相对路径会拒绝）。
5. **冒烟**：`Create a sphere and place it above the cube`；再用 `get_scene_info`/Python 回读验证对象是否真实存在。
6. **安全项**：Blender 里先 `Ctrl+S`；9876 只绑 localhost；不需要资产库就把 Poly Haven 关掉。

### 阶段 2：按需加装（只增不减）

| 需求 | 加装 |
|---|---|
| 视觉回读 / 多角度检查 | mcp-for-blender 的 `look`，配 qwen36 视觉做验收回合（qwen25vl 可作快速预览） |
| 免费 CC0 资产（HDRI/贴图/低模） | mcp-for-blender 的 Poly Haven / Poly Pizza（Poly Pizza 需免费 key） |
| 文本/图片生 3D，纯本地 | 本机 ComfyUI + Hunyuan3D（关掉 mcp-for-blender 的云端 `generate_3d`） |

### 明确不做

- 不把 Blender 的 9876 端口暴露到局域网（socket 无鉴权，等同于远程执行 Python）。
- 不用 GUI 像素级自动化充当 Blender 的主操作手。
- 不用未验证 projector 的 GGUF 视觉模型做 Blender 场景判读。

---

## 五、风险与验收清单

| 风险 | 处置 |
|---|---|
| 官方 MCP 执行任意代码 | 存盘 + 可选 VM；正式项目单独 `.blend` 副本 |
| qwen36 长上下文退化 | 工具 schema 预算 6000 字符以内；单轮工具结果超限先压缩 |
| Blender 5.1 插件兼容 | 只装 1.0.3 及以上；升级 Blender 后重装扩展 |
| 显存互斥 | 任务前检查 :8188 / :8080；渲染时先停 ComfyUI 与 MOSS |
| 云端 3D 生成不自觉产生费用 | 关掉 `generate_3d` 的 Premium/API 开关，仅用本地 Hunyuan3D |

验收口径：
1. 官方 MCP 能完成"建球→移到立方体上方→读回场景确认"三步，且不弹错误。
2. `look` 能返回可读的渲染图（若装阶段 2）。
3. 任一环节失败，保留原始日志与截图，不静默降级到云端。

---

## 六、参考来源

- [Blender Lab MCP Server（官方）](https://www.blender.org/lab/mcp-server/)
- [Blender MCP Server 源码](https://projects.blender.org/lab/blender_mcp)
- [mcp-for-blender（ahujasid）](https://github.com/ahujasid/blender-mcp)
- [Blender MCP 2026 路线对比（3D-Agent 侧）](https://3d-agent.com/blender-mcp)
- [3D-Agent 安装要求](https://3d-agent.com/docs/install)
