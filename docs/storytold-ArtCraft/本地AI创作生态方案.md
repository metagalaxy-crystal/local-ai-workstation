# 基于 storytold 生态的本地 AI 创作方案

> 2026-10-19 · 适配环境：Windows · 8GB 显存 · 已有 llama.cpp 本地 LLM（nanbeige/deepseek/qwen25vl 等）· 已有 ComfyUI · d:\models 模型盘

## 〇、可行性结论

**可行，但"AI 生成"与"本地编辑"要分开看：**

| 能力 | 是否本地 | 说明 |
|---|---|---|
| Craft 应用编辑（PPT/图像/PDF/表格…） | ✅ 纯本地 | deckcraft/photocraft 等是原生 Rust 桌面应用，不依赖云 |
| AI 图像/视频生成（ArtCraft 内置 62 模型） | ❌ 默认云端 | 需 provider API key，按量付费 |
| AI 能力本地化 | 🔧 需自建 | `artcraft-services`（后端）与 `craft-ai-integrations`（接入层）均开源，可自指向本地推理端点 |

**现实路径**：本地编辑用 Craft 全家桶，AI 生成用你已有的 ComfyUI + 本地 LLM 补上，两者用文件/脚本粘合。

## 一、总体架构

```
┌─ 编排层（你已有的本地 LLM, llama.cpp server）──────────┐
│  qwen/deepseek 等 → 大纲、文案、提示词、脚本生成        │
└──────┬───────────────────────┬────────────────────────┘
       │ 文本/指令              │ 提示词
┌──────▼─────────┐    ┌────────▼─────────┐    ┌─────────────────┐
│ Craft 应用家族   │    │ ComfyUI（已有）    │    │ 可选: 自建        │
│ deckcraft  PPT  │    │ SDXL / FLUX Q4   │    │ artcraft-services│
│ photocraft 修图 │    │ 本地图像生成       │    │ + craft-ai-      │
│ gridcraft  表格 │    │ (8GB 显存独占)    │    │   integrations   │
│ pdfcraft   PDF │    └──────────────────┘    │ 接本地端点        │
│ craft-launcher  │                            └─────────────────┘
└────────────────┘
粘合方式：LLM 生成 .pptx/.md/脚本 → 用 deckcraft 打开精修；
         ComfyUI 出图 → photocraft 后期 → deckcraft 插图
```

## 二、三档实施方案

### 方案 A：零构建尝鲜（磁盘 ≈ 5–10 GB）
1. 装 [craft-launcher](https://github.com/storytold/craft-launcher) 或直接下各 app 的 release：deckcraft、photocraft、pdfcraft、gridcraft
2. AI 生成继续走你现有 ComfyUI（本地）或云端 API
3. 适合先验证 Craft 应用的成熟度（注意：全部仅 3 周龄，bug 多）

### 方案 B：混合本地创作流（推荐，新增磁盘 ≈ 20–35 GB）
1. 方案 A 全部应用
2. 图像模型按需二选一（适配 8GB 显存）：
   - **SDXL fp16**（舒适区）：底模 ~7 GB + VAE ~0.3 GB
   - **FLUX.1 dev GGUF Q4**（上限）：unet ~6.8 GB + t5xxl Q4 ~3 GB + clip_l ~0.25 GB + VAE ~0.3 GB（慢，出图分钟级）
3. PPT 管线：本地 LLM 生成大纲/讲稿 → python-pptx 或 pptxgenjs 合成 .pptx → deckcraft 打开精修 → photocraft 处理配图
4. 显存纪律：ComfyUI 与 MOSS-Music 等独占进程互斥，切换前先停对方（既有约束）

### 方案 C：全自建（把 AI 接进 ArtCraft，磁盘 ≈ 60–120 GB）
1. clone `artcraft` monorepo + `artcraft-services` + `craft-ai-integrations`
2. Rust 工具链 rustup/cargo：~2–3 GB
3. 构建：Rust 大型 workspace 的 target 缓存极大，debug 构建 20–40 GB，源码 ~1–2 GB
4. 后端自建（数据库 + 存储）：~3–8 GB
5. 改造 craft-ai-integrations，把 provider 端点指向本地：llama.cpp server（文本）+ ComfyUI API（图像）
6. 收益：ArtCraft 的 2D/3D 合成、画布编辑能力 + 全本地推理；代价：构建重、代码 3 周龄、需跟进上游频繁变更

## 三、磁盘空间明细

| 项目 | 大小 | 方案 |
|---|---|---|
| craft-launcher | ~0.3 GB | A/B/C |
| 每个 Craft 应用（deckcraft/photocraft/pdfcraft/gridcraft…） | ~0.3–1 GB/个，全家桶 ≈ 4–8 GB | A/B/C |
| ArtCraft 桌面版（旗舰 IDE） | ~1–2 GB | 可选 |
| SDXL 底模 + VAE | ~7.3 GB | B（推荐） |
| FLUX.1 dev Q4 全套（unet+t5xxl Q4+clip_l+VAE） | ~10.4 GB | B（进阶） |
| 视频生成（LTX-Video / Wan2.1-1.3B Q4） | ~3–6 GB（8GB 显存仅勉强，慢，不推荐） | B 可选 |
| PPT 专用文案 LLM（若新增 7–9B Q4 GGUF） | ~5–6 GB（现有模型可复用则免） | B 可选 |
| Rust 工具链 | ~2–3 GB | C |
| artcraft monorepo 源码 | ~1–2 GB | C |
| 构建缓存 target/（debug） | ~20–40 GB | C |
| artcraft-services + 数据库 + 依赖 | ~3–8 GB | C |
| **合计** | **A ≈ 5–10 GB · B ≈ 20–35 GB · C ≈ 60–120 GB** | |

> 建议预留：方案 B 留 50 GB 余量（模型更新/缓存）；方案 C 留 150 GB。

## 四、风险与注意

1. **成熟度**：Craft 家族全部 2026-09-30 后创建，open issues 数百至数千，docx/pptx/xlsx 格式兼容性未经广泛验证——重要文件先备份，别当生产力主力。
2. **star 异常**：3 周 6.8 万 star 的增长曲线不正常，社区真实采用度待观察。
3. **净室重写 ≠ 格式完美兼容**：对 .pptx 复杂动画、.xlsx 宏的支持大概率有缺口。
4. **视频生成**：8GB 显存本地跑视频模型不现实；要么云端 API，要么放弃此能力。
5. **跟进成本**：上游更新极频繁（当日多个仓库有提交），方案 C 需定期 rebase。

## 五、推荐路线

**先 B 后 C**：用方案 B（≈30 GB）立刻形成"本地 LLM 文案 + ComfyUI 出图 + Craft 应用编辑"的闭环；验证 deckcraft/photocraft 稳定后，再决定是否投入方案 C 把 AI 深度接进 ArtCraft。
