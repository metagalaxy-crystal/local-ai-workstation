# GitHub `storytold` 组织项目调研

> 调研日期：2026-10-19 · 数据来源：GitHub API（org:storytold，共 55 个公开仓库）+ 官网 getartcraft.com + 公开报道

## 一、组织背景

- **storytold** 是 StoryTold / ArtCraft 团队的 GitHub 组织，前身即知名 TTS 网站 **FakeYou**（fakeyou.com，原 vo.codes）与 storyteller.ai 的开发团队。
- 创始人 Thomas，在做了约 3 年 storyteller.ai CEO 后，约一年前创立 **ArtCraft**，定位"艺术家的 IDE"（The IDE for artists）。
- 当前战略：**全线转向 Rust**，以"clean-room（净室重写）"方式打造一整套开源创意工具链，对标 Adobe Creative Cloud / Microsoft Office / Avid / Autodesk / Figma。
- 官网：[getartcraft.com](https://getartcraft.com/)，桌面端支持 macOS / Windows（Linux 可自行编译），旗舰项目 MIT/Apache-2.0 双许可。

## 二、项目全景（按 Star 排序，截至 2026-10-19）

### 第一梯队："Craft" 应用家族（2026-09-30 起集中创建，全部纯 Rust）

| 仓库 | Star | 对标产品 | 说明 |
|---|---|---|---|
| [photocraft](https://github.com/storytold/photocraft) | 68.0k | Photoshop | 照片编辑器 |
| [artcraft](https://github.com/storytold/artcraft) | 33.3k | —（旗舰） | AI 图像/视频创作 IDE（2022 年创建） |
| [pdfcraft](https://github.com/storytold/pdfcraft) | 16.1k | Acrobat | PDF 阅读/编辑器 |
| [filmcraft](https://github.com/storytold/filmcraft) | 15.0k | Premiere | 非线性视频编辑器 |
| [wordcraft](https://github.com/storytold/wordcraft) | 14.6k | Microsoft Word | 净室重写 |
| [lightcraft](https://github.com/storytold/lightcraft) | 13.8k | Lightroom | 非破坏性 RAW 照片编辑 |
| [vectorcraft](https://github.com/storytold/vectorcraft) | 9.9k | Illustrator | 矢量图/SVG 工具 |
| [effectcraft](https://github.com/storytold/effectcraft) | 7.4k | After Effects | 动效与合成 |
| [cadcraft](https://github.com/storytold/cadcraft) | 5.9k | AutoCAD | CAD 制图 |
| [gridcraft](https://github.com/storytold/gridcraft) | 5.8k | Microsoft Excel | 电子表格 |
| [designcraft](https://github.com/storytold/designcraft) | 4.4k | InDesign | 版面/印刷设计 |
| [deckcraft](https://github.com/storytold/deckcraft) | 3.8k | PowerPoint | 演示文稿 |
| [craft-launcher](https://github.com/storytold/craft-launcher) | 3.4k | Creative Cloud 启动器 | 统一应用启动器 |
| [soundcraft](https://github.com/storytold/soundcraft) | 3.3k | Avid Pro Tools | 音频工作站 |
| [figcraft](https://github.com/storytold/figcraft) | 2.7k | Figma | 界面设计与原型 |
| [AniCraft](https://github.com/storytold/AniCraft) | 42 | —（2D 动画） | 2026-10-14 新建，最年轻成员 |

### 第二梯队：基础设施与配套

| 仓库 | Star | 作用 |
|---|---|---|
| [artcraft-services](https://github.com/storytold/artcraft-services) | 1.2k | 后端 + Web 前端（Rust） |
| [artcraftx](https://github.com/storytold/artcraftx) | 954 | ArtCraft-X（实验线） |
| [craft-fonts](https://github.com/storytold/craft-fonts) | 362 | 家族字体 |
| [craft-libs](https://github.com/storytold/craft-libs) | 307 | 共享 Rust 库 |
| [craft-repo-status-app](https://github.com/storytold/craft-repo-status-app) | 131 | PR/构建状态看板 |
| [craft-ai-integrations](https://github.com/storytold/craft-ai-integrations) | 55 | AI 接入层：provider/key/client/egui 组件 |
| [craft-common-actions](https://github.com/storytold/craft-common-actions) | 57 | CI 公共 actions |
| [crafthub](https://github.com/storytold/crafthub) / [craft-contrib](https://github.com/storytold/craft-contrib) / [craft-launcher-assets](https://github.com/storytold/craft-launcher-assets) | <40 | 生态配套 |
| [indd-utils](https://github.com/storytold/indd-utils) | 37 | 免 InDesign 读 INDD 转 IDML |
| [photocraft-corpus](https://github.com/storytold/photocraft-corpus) | 142 | 测试语料 |

### 第三梯队：历史项目（2020–2025，多数停更/归档）

- **语音/TTS（FakeYou 时期）**：storyteller-ml（Tacotron）、vits-finetuning、realtime-voice-conversion（已归档）、fakeyou-recast、discord-vocodes、voder-proxy（已归档）、redirect-vocodes（vo.codes→fakeyou.com 跳转）
- **UE5 动捕/VTuber 实验**：HyperJail、AnimationTest、StreamTwo、EventCenterPlugin、ActorSpawningPlugin、CloudCamPlugin、cloudcam、point-generator（已弃用）、xsens-packet-send、motion-capture-data、k4a-sys-temp
- **Rust/Bevy 探索**：bevy-mocap、storyteller-bevy、hanashi-graphics-demo
- 其他：FineTrainers-Conditioning（扩散模型微调条件化）、cloud-worker、github-media、placeholder-artcraft（已归档）等

## 三、旗舰项目 ArtCraft 详析

**定位**：交互式 AI 图像/视频创作 IDE —— "把 prompting 变成 crafting"。先搭场景再生成，强调可控性、可复现性。

**核心能力**（README 实证）：
- 2D/3D 合成：Image to Location（虚拟场景复用）、3D/2D 图像合成、Image to 3D Mesh、角色摆姿、Kitbash 场景搭建、角色身份迁移、背景移除、混合资产创作
- 提示流：文生图、提示式图像编辑（Nano Banana Pro / GPT Image）、画布编辑（蒙版/局部重绘）、图生视频
- **模型聚合**：内置 62 个模型目录 —— 图像 16（Nano Banana、GPT Image、FLUX、Seedream 系）、视频 25（Seedance、Kling、Veo、Sora、Vidu、MiniMax、Flux）、音频 5（Suno、Seed Audio）、3D 网格 11（Hunyuan 3D、Tripo3D、Meshy、Rodin）、世界/高斯泼溅 5（Marble、TripoSplat）；另支持 Grok / Midjourney / Sora / World Labs 等第三方 provider，计划接入 Kling、Google、Runway、Luma 及 OpenArt/Freepik 聚合订阅
- **许可**：MIT / Apache-2.0 双许可

## 四、发展脉络

```
2020–2022  FakeYou 时代：TTS/语音转换 + UE5 动捕/VTuber 实验（Python/C++/Rust 混杂）
2023–2025  Bevy/Rust 图形学探索 + storyteller.ai（3D 虚拟片场）
2022-03    artcraft 仓库创建（早期形态）
2026-09-11 artcraft-services 上线（后端/Web）
2026-09-30 ~ 10-14  "Craft 家族大爆发"：3 周内连发 16 个净室 Rust 应用，覆盖 Adobe 全家桶 + Office 三件套 + Pro Tools + AutoCAD + Figma
```

## 五、技术观察

1. **全 Rust 统一栈**：应用、库、启动器、后端全部 Rust，UI 层用 egui（craft-ai-integrations 实证），共享 craft-libs / craft-fonts。
2. **"净室重写"策略**：所有对标应用均声明 clean-room reimplementation，规避版权风险；配套 indd-utils 等格式解析器补生态位。
3. **AI 是横切层而非单点**：craft-ai-integrations 作为独立仓提供统一 provider/key/客户端管理，供所有 Craft 应用复用。
4. **数据疑点（需留意）**：photocraft 等仓库创建于 2026-09-30，三周内即获 6.8 万 star、1.2 万 fork、2800+ open issues，增长速度远超自然曲线，存在营销冲榜或数据异常的可能；建议以代码提交质量和 issue 讨论深度而非 star 数判断项目成熟度。
5. **issue 负载高**：新仓普遍带着数百至数千 open issues（gridcraft 1097、wordcraft 1230），反映"先发布后打磨"的激进节奏。

## 六、结论

storytold 是从 AI 语音（FakeYou）起家、经 3D 虚拟片场（storyteller.ai）演进而来的团队，现以 ArtCraft 为旗舰，正在执行一个罕见的大胆赌注：**用纯 Rust 净室重写整个创意软件生态**，并以 AI 模型聚合（62+ 模型、多 provider）作为差异化武器。项目活跃度极高（几乎所有仓库当日有更新），但 Craft 家族普遍"年轻且 issue 积压"，成熟度待验证。值得持续跟踪的信号：各 Craft 应用的 release 可用性、craft-libs 的架构复用程度、以及 star 异常增长背后的真实社区采用率。
