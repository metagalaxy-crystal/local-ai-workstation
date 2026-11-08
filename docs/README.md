# 测试报告与文档汇总

模型测试报告、云端部署文档与项目资料统一存放在此目录。

## 测试报告

| 文档 | 内容 |
|---|---|
| [云端vs本地模型对比.md](云端vs本地模型对比.md) | T0~T7 全维度对比：速度探针/写作/数学/代码/摘要/问答/多模态 |
| [本地模型推理能力测试.md](本地模型推理能力测试.md) | 10 道多步逻辑/数学/代码陷阱题硬推理专项（自动判分） |
| [本地模型编程能力测试.md](本地模型编程能力测试.md) | t1~t5 编码任务实测，生成代码真实运行验证 |
| [本地模型英文基准测试.md](本地模型英文基准测试.md) | 英文卷单独归档，与中文测试完全分离 |
| [工具调用测试报告.md](工具调用测试报告.md) | 本地模型 Craft 工具调用能力实测 |

## Strata 部署与运维（[strata\](strata/)）

| 文档 | 内容 |
|---|---|
| [部署方案.md](strata/部署方案.md) / [部署记录.md](strata/部署记录.md) | vLLM 服务部署方案与实施记录 |
| [API密钥管理方案.md](strata/API密钥管理方案.md) | 鉴权 key 管理 |
| [局域网使用说明.md](strata/局域网使用说明.md) | 内网访问方式 |
| [优化方案.md](strata/优化方案.md) | 服务调优 |

## Agent / Blender 方案

| 文档 | 内容 |
|---|---|
| [Mage-VL-Cowork本地部署方案.md](Mage-VL-Cowork本地部署方案.md) | Mage-VL-Cowork 桌面操控模型：三档部署方案、本机 4bit 实测结果、决策退化诊断 |
| [Blender本地适配调研.md](Blender本地适配调研.md) | Blender 官方 MCP / mcp-for-blender / 3D-Agent / Claude connector 四路线本机适配评估 |

## storytold-ArtCraft 资料（[storytold-ArtCraft\](storytold-ArtCraft/)）

调研、方案、使用指南与测试工作簿（Craft 目录本体只保留调用必需文件）。

## 原始数据

`bench_results\`：各模型基准原始输出与 summary.json（中英文卷、旧配置归档齐全），由 `d:\models\scripts\strata\bench\bench_*.py` 生成。

> 2026-10-22 整理：`d:\models\云端strata相关文档\` 目录已移除，内容分别迁入此处（报告/数据/部署文档）与 `scripts\strata\bench\`（基准脚本）。
