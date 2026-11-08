# 云端 Strata vs 本地模型 · 普适性能对比测试报告

> 测试日期：2026-10-19（2026-10-20 增补 lfm24b / nemotron 两款）｜ 测试脚本：[bench_universal.py](bench_universal.py)（可重复执行）
> 原始输出：bench_results\\\<模型名>\\\ 目录全文留档
> 测试性质：**普适能力测试**（与具体业务场景无关），覆盖速度/写作/推理/代码/长文/知识/多模态七个维度
> 被测：云端 1 款 + 本地 9 款（本机 d:\models\models\text 下全部 text 模型；2026-10-20 新增 lfm24b / nemotron）

## 一、被测对象

| 编号 | 模型 | 规模 | 部署 | 视觉 | 测试配置 |
|---|---|---|---|---|---|
| **strata**（云端） | Qwen3.8-Flash-Next | 176B MoE | 局域网主机（i7-14700/64GB/RTX 3050 8GB/NVMe） | ✅ | IQ2_XS，`reasoning_effort=low` |
| **qwen35b** | Qwen3.6-35B-A3B | 35B MoE | 本机 llama.cpp（`-ngl 99 --cpu-moe --load-mode none`，调优后） | ✅（BF16 mmproj） | Q4_K_M，关 thinking |
| **ornith** | Ornith-1.0-9B-heretic-MTP | 9B | 本机 llama.cpp（MTP 投机解码，调优后） | — | Q4_K_M |
| **deepseek** | DeepSeek-R1-0528-Qwen3-8B | 8B | 本机 llama.cpp | — | Q4_K_M，关 thinking |
| **lfm** | LFM2.5-8B-A1B | 8B MoE（激活1B） | 本机 llama.cpp | — | Q4_K_M |
| **qwen25vl** | Qwen2.5-VL-7B-Instruct | 7B | 本机 llama.cpp + mmproj | ✅ | Q4_K_M |
| **minicpm** | MiniCPM-V-4.6 | ~8B | 本机 llama.cpp + mmproj | ✅ | Q4_K_M |
| **nanbeige** | Nanbeige4.2-3B | 3B | 本机 llama.cpp | — | Q4_K_M，关 thinking |
| **lfm24b**（10-20 新增） | LFM2-24B-A2B | 24B MoE（激活2B） | 本机 llama.cpp（`-ngl 99 --n-cpu-moe 21 --load-mode none`，调优后） | — | Q4_K_M，非思考模型 |
| **nemotron**（10-20 新增） | Nemotron-3-Nano-Omni-30B-A3B | 30B MoE（激活3B） | 本机 llama.cpp（`-ngl 99 --cpu-moe --load-mode none` + F16 mmproj） | ✅（图/音/视频） | IQ4_XS，关 thinking |

本机硬件：RTX 5060 Laptop 8GB / 32GB RAM；局域网 RTT 约 6ms（对结果影响可忽略）。

## 二、速度总览（tok/s，T0 探针中位 / T4 长文；2026-10-19 调优后复测，▲=有提升，新旧对照见第七节；lfm24b/nemotron 为 2026-10-20 新增）

| 排名 | 模型 | T0 探针 | T4 长文 | 量级 |
|---|---|---|---|---|
| 1 | minicpm | 191.4 | 238.6 | ~200 |
| 2 | lfm | 173.6 | 208.7 | ~190 |
| 3 | ornith ▲ | 72.7 | 83.0 | ~78 |
| 4 | deepseek | 60.8 | 60.6 | ~61 |
| 5 | qwen25vl | 59.8 | 57.0 | ~58 |
| 6 | nanbeige | 59.4 | 59.2 | ~59 |
| 7 | **strata（云端）** | **41.4** | **35.8** | **~38** |
| 8 | lfm24b（新） | 37.9 | 19.2 | ~35 |
| 9 | qwen35b ▲ | 34.2 | 24.1 | ~30 |
| 10 | nemotron（新） | 30.4 | 25.7 | ~30 |

## 三、能力结果总表（✓=自动判定通过；写作/摘要/创造力为人工评分 1-5。自动判定项与 T6 耗时为 2026-10-19 调优后复测值；人工评分沿用首轮——调速不改变权重与质量；lfm24b / nemotron 为 2026-10-20 首测值）

| 模型 | T2 数学 | T3 代码（实跑） | T5 知识（3题） | T1 写作 | T4 摘要 | T6 多模态 | T7 创造力 |
|---|---|---|---|---|---|---|---|
| **strata** | ✓ | ✓ PASS | 3/3 | **5.0** | **5.0** | **5.0**（21.7s） | **5.0** |
| qwen35b | ✓ | ✓ PASS | 2/3* | **5.0** | **5.0** | **5.0**（27.1s，原 166s） | **4.8** |
| nanbeige | ✓ | ✓ PASS | 2/3* | 4.5 | 4.5 | — | 4.0 |
| **lfm24b**（新） | ✓ | ✓ PASS | 2/3* | 4.0 | 4.5 | —（纯文本） | 3.8 |
| **nemotron**（新） | ✓ | ✓ PASS | 2/3* | 3.5 | 4.5 | 5.0（25.0s） | 3.8 |
| qwen25vl | ✓ | ✓ PASS | 2/3* | 4.0 | 4.0 | 4.0（4.8s） | 2.8 |
| minicpm | ✓ | ✗ 混入英文散文 | 3/3 | 3.5 | 2.5 | 4.0（1.9s） | 2.0 |
| ornith | ✓ | ✓ PASS | 2/3* | 2.0 | 1.5 | — | 2.8 |
| deepseek | ✓ | ✗ 只分析不写码 | 2/3* | 3.5（截断） | 2.5（截断） | — | 3.5 |
| lfm | ✗† | ✓ PASS | 2/3* | 1.5 | 1.5 | — | 2.0 |

> T7 创造力 = 微小说（指定开头"她在第十四次重生后，决定不再救他。"+意外转折）与 App 创意命名两题均值。亮点：strata 微小说仅 87 字、转折冷峻完整（"她低头，才发现自己手腕上有一道伤口——第十四道"）；qwen35b 的"微型炸弹在她口袋"设计同样出色。minicpm/lfm 命名题擅自改用英文名（题面是面向中国老年人的 App）；ornith 创意不错但思维链泄进输出。新增两款：lfm24b 转折偏抒情说教、命名贴合老年场景（智慧老友/点亮生活）；nemotron 反转冷峻（"而他，永远被困在时间的循环里"）但命名平淡。

> *T5 自动匹配对数字格式敏感（如"30万公里/秒"vs"299,792,458米/秒"），漏判不代表答错；人工复核以首轮为准（首轮仅 qwen25vl 光速题单位错 1000 倍为真实错误，本轮未复现）。†lfm 数学本轮未自动通过（首轮通过），属输出波动非调优回退。qwen35b 复测 T5 2/3 同为格式漏判。lfm24b / nemotron 的 2/3 经人工复核三题全对（光速/红楼梦/404），同为格式漏判。

## 四、关键发现

1. **可靠性天花板：云端 Strata 与本地 Qwen35B 并列**，八项全优（含创造力与多模态）。**参数调优后 Qwen35B 从 7.3 → ~34 tok/s（5 倍，原理同 Strata 的 MoE 专家卸载，详见第七节），本地从此也有可用的质量档**；Strata 40-50 tok/s 仍是质量档最快，且不占本机显存。
2. **参数调优的红利分布**：只对 MoE 调度（qwen35b，5 倍）与投机解码（ornith 自带 MTP 头，56 → ~78 tok/s，+40%）有效；稠密 GPU 驻留模型（nanbeige/deepseek/lfm/qwen25vl/minicpm）早已满速，flash-attn/KV 量化在 8K 短上下文无感（详见第七节）。
3. **3B 黑马 Nanbeige**：自动判定全过、写作摘要 4.5 分、创造力 4.0、~60 tok/s，是本地文本模型里**性价比之王**。
4. **多模态不是云端独占**：本地 MiniCPM-V（1.9s/张）、Qwen2.5-VL（4.8s/张）快速看图；qwen35b 调优后看图从 166s 降到 27.1s（精细但偏慢）；描述精细度 strata ≈ qwen35b > qwen25vl ≈ minicpm。**快速看图用本地 VL，精细质检用 Strata**。
5. **创造力格局**：strata（5.0）与 qwen35b（4.8）断档领先——同样给定开头，strata 87 字完成冷峻反转，多数本地模型要么平庸套路（qwen25vl）、要么违背题意（minicpm 没用指定开头、lfm 一句话跑题）、要么思维链泄漏（ornith）。
6. **DeepSeek 截断真相**：不是服务中断，是**撞 max_tokens 上限**——关 thinking 后它习惯先长篇分析再给结果，900 token 额度被前置分析吃光（server 日志 `n_gen=900, truncated=0` 正好顶满），正文写到一半即被截断；T3 甚至 900 token 全花在分析上、代码一字未出。对策：加大 max_tokens 或开 thinking。
7. **输出卫生问题**：ornith/lfm 把英文思维链泄进正文；deepseek 关 thinking 后啰嗦截断；minicpm 代码题混入英文散文、创造力题擅自改用英文。
8. **qwen25vl 知识可靠性**（首轮光速单位错 ×1000，本轮未复现），7B 量级仍需留意。
9. **新增两款（2026-10-20）同样吃到 Strata 式 MoE 卸载红利**：LFM2-24B（38 层 MoE 中前 21 层专家留内存）~38 tok/s、Nemotron-30B（23 层专家全留内存）~30 tok/s，调优细节见第九节。**LFM2-24B 补齐 LFM 家族质量短板**（写作/摘要 4.0/4.5 vs LFM2.5-8B 的 1.5/1.5，中文输出干净），但速度只有自家 8B 的 1/5；**Nemotron 是本地第二款"视觉+agent 双全"模型**（T6 5.0、工具调用 3/3），弱点在中文写作（3.5，偶发英文作答倾向）。

## 五、选型建议

| 任务 | 首选 | 次选 | 备注 |
|---|---|---|---|
| 中文成稿/摘要/长文 | **strata（云端）** | qwen35b（本地，调优后 ~34 tok/s） | lfm24b 亦可（~38 tok/s，摘要 4.5）；纯速度优先可退到 nanbeige |
| 创意写作 | **strata（云端）** | qwen35b（本地可用） | 两者创造力断档领先；lfm24b/nemotron 3.8 分可用但平淡 |
| 代码生成 | **strata（云端）** | qwen35b / nanbeige / ornith | 本地几款实跑验证也能过，但需容忍偶发失控 |
| 快速草稿/短问答 | nanbeige / ornith（投机解码 ~78） | minicpm / lfm | ~200 tok/s 即时响应选 minicpm |
| 看图（快速） | **minicpm / qwen25vl（本地）** | — | 2-5 秒出描述 |
| 看图（精细质检） | **strata（云端）** | qwen35b（27s/张，偏慢） | nemotron 亦可（25s/张，细节准，偶发英文作答） |
| 数学/推理 | 均可（基本全对） | — | 按速度选 |
| 不推荐用途 | lfm（中文输出脏）、deepseek 关 thinking（失控）、lfm24b 做 agent（工具调用仅 1/3，见工具调用测试报告） | | |

**一句话总结**：调优后本地完成闭环——质量档 qwen35b（~34 tok/s，质量与云端并列 5.0）与 lfm24b（~38 tok/s，LFM 家族质量补全）、中速档 ornith（~78 tok/s 投机解码）/nanbeige（~59 tok/s）、极速档 minicpm/lfm（~200 tok/s）、全模态 agent 档 nemotron（~30 tok/s，视觉/音频 + 工具调用全过）；云端 Strata（40-50 tok/s）的价值转向**不占本机显存的质量档主力 + 176B 天花板 + 精细视觉质检**，与本地互补而非替代。

## 六、复现方法

```powershell
# 云端（服务需在主机上先启动 run-iq2_xs.bat + run-gateway.bat）
python bench_universal.py --preset strata

# 本地（调优参数已固化到 d:\models\scripts\llama_cpp\，双击对应 start.bat 即最优配置；
# 端口与注册表不一致时用 start_server.py <key> --port <端口>，端口见 bench 脚本 PRESETS）
python bench_universal.py --preset <nanbeige|qwen35b|ornith|deepseek|lfm> --skip-mm
python bench_universal.py --preset <qwen25vl|minicpm>           # 视觉模型测多模态
python bench_universal.py --preset lfm24b --skip-mm             # 2026-10-20 新增（纯文本）
python bench_universal.py --preset nemotron                     # 2026-10-20 新增（自动关 thinking，含 T6 视觉）
```

## 七、本地模型参数调优后全量复测（2026-10-19）

对 7 款本地 text 模型逐一应用 llama.cpp 调优参数并重跑全量测试（T0-T7）。**结论：参数调优只对"瓶颈在内存/调度"的模型有效，纯 GPU 驻留的稠密模型已是满速。**

| 模型 | 调优措施 | 速度（旧 → 新） | 全量测试总耗时（旧 → 新） | 提升 |
|---|---|---|---|---|
| **qwen35b** | `--cpu-moe --load-mode none` | 7.3 → **34-39 tok/s** | **~800s → ~115s** | **5 倍以上** |
| **ornith** | `--spec-type draft-mtp --spec-draft-n-max 3 -fa on`（MTP 投机解码，草稿接受率 ~0.7） | 56 → **72-83 tok/s** | ~103s → ~92s | **+40%** |
| nanbeige | `-fa on -ctk q4_0 -ctv q4_0` | 65 → 59-65 tok/s | ~48s → ~45s | 持平 |
| deepseek | `-fa on` | 62 → 61-63 tok/s | ~100s → ~100s | 持平 |
| lfm | `-fa on` | 215 → 174-215 tok/s | ~33s → ~32s | 持平 |
| qwen25vl | `-fa on --mmproj-offload` | 65 → 60-67 tok/s | ~30s → ~28s | 持平 |
| minicpm | `-fa on --mmproj-offload` | 230 → 191-238 tok/s | ~18s → ~16s | 持平 |

要点：
- **两个真实赢家**：qwen35b（MoE 专家卸载+权重常驻内存，原理同 Strata）和 ornith（自带 MTP 多头做投机解码，白捡 40%）。
- 稠密小模型（nanbeige/deepseek/lfm/qwen25vl/minicpm）全量驻留 GPU，早已满速，flash-attn/KV 量化在 8K 短上下文下无感（长上下文下 KV 量化省显存仍有价值）。
- 新结果在 `bench_results\<模型>\`，旧结果完整保留在 `bench_results\<模型>_旧配置\`（qwen35b 为 `qwen35b_旧配置ngl24\`）；每项测试的耗时、tok/s 见各目录 `summary.json`。
- qwen35b 最优启动参数已固化到 `d:\models\scripts\llama_cpp\models.json`（key: qwen36）及 `qwen36\start.bat`、`qwen36\README.md`；ornith 投机解码参数注册表原本就有，本次实测确认有效。
- **固化规则（2026-10-19）**：持平模型按"谁快留谁"择优——实测 `-fa on` 对 nanbeige/deepseek/lfm/qwen25vl/minicpm 不是提速项（lfm 探针 212.8→173.6、qwen25vl 66.8→59.8 反而拖慢），已从注册表移除；nanbeige 的 `-ctk/-ctv q4_0` 一并移除（同轮变慢）；qwen36 的 `-fa on` 也移除（最快实测配置不含 fa）。ornith 保留 `-fa on + 投机解码`（该组合是其最快实测）。今后双击各模型 `start.bat` 即为各自最快配置。

业务场景（分镜脚本生成）的专项对比另见 `d:\models\sample\铁锈海的女儿\06_compare\llm_bench.md` 第 6 节。

## 八、附：本地 Qwen35B 的 Strata 式优化（2026-10-19 实测）

**原理**：Strata 快的核心不是硬件，而是 MoE 专家卸载——176B 模型每 token 只激活约 3-4B 参数，把"注意力+共享层"放显存、全部专家权重放内存（热专家再缓存进显存），瓶颈从显存容量转为内存带宽；IQ2_XS 量化把权重压到 ~55GB 正好装进 64GB 内存，NVMe SSD 兜底冷专家。

本地 Qwen35B（35B MoE，激活 ~3B）用同样思路，llama.cpp 原生支持（2026-10-19 三轮实测）：

| 配置 | 速度（客户端实测） | 结论 |
|---|---|---|
| `-ngl 24`（整层切分） | 7.3 tok/s | ❌ 注意力/专家混在 CPU，互相拖累 |
| `-ngl 99 --cpu-moe`（专家全留内存） | 25.5-29.8 tok/s | 思路对了，但专家权重走 mmap 按需调页，被系统挤出后回读 SSD |
| `-ngl 99 --cpu-moe --load-mode none` | **37.5-39.4 tok/s（server 端 40.5）** | ✅ **最优**：专家权重启动时全量载入 RAM 常驻 |
| 上述 + `--flash-attn on --threads 16` | 31.4-34.2 tok/s | ❌ 砍掉 E 核反而拖慢专家矩阵乘，默认 24 线程最优 |

```powershell
# 最终推荐启动命令（质量 5.0 不变，速度 7.3 → ~39 tok/s，提升 5 倍以上）
llama-server.exe -m Qwen3.6-35B-A3B-Q4_K_M.gguf `
  -ngl 99 --cpu-moe --load-mode none -c 8192 --jinja --port 8093
```

要点：8GB 显存的甜点位是 **--cpu-moe 全量卸载**（`--n-cpu-moe 24` 半卸载实测降到 10-11 tok/s，显存放不下半个专家库导致换页颠簸）；`--load-mode none` 是关键一环（19.7GB 模型在 32GB 内存下必须常驻，否则 mmap 页面被挤出）；视觉 mmproj 可与此方案叠加。还想更快可换 Q3_K_M/IQ3 量化（权重少 ~35%，预计 50+ tok/s，质量略降，需另行下载）。优化后本地 Qwen35B 与云端 Strata（40-50 tok/s）基本同档。

## 九、新增模型接入与调优记录（2026-10-20）

两款大 MoE 模型接入本机（GGUF 经 hf-mirror 直下并逐字节校验；配置已固化到 `d:\models\scripts\llama_cpp\models.json` 与各自 `start.bat` / `chat.bat` / `README.md`，双击即最优配置）：

| 模型 | 结构 | 最优启动参数（端口） | 实测速度 | 调优要点 |
|---|---|---|---|---|
| **lfm24b**（LFM2-24B-A2B，14.4GB Q4_K_M） | 24B MoE 激活 2B，38 个 MoE 层（blk.2-39），每层专家约 340MB | `-ngl 99 --n-cpu-moe 21 --load-mode none -t 6 -c 16384`（8097） | tg 44 tok/s，pp 62-72；T0 37.9 | `--cpu-moe` 全卸载 pp 仅 49（劣）；`-t 16` 长上下文 tg 掉到 26.3（劣）；前 21 层专家留内存、其余上 GPU 恰好塞满剩余显存 |
| **nemotron**（Nemotron-3-Nano-Omni-30B-A3B，19.5GB IQ4_XS + 1.5GB F16 mmproj） | 30B MoE 激活 3B，23 个 MoE 层，每层专家约 680MB；Mamba 混合架构；图/音/视频 omni | `-ngl 99 --cpu-moe --load-mode none -t 6 -c 16384 --jinja` + mmproj（8098） | tg ~39 tok/s；T6 视觉 32 tok/s | 23 层 × 680MB 远超剩余显存，部分卸载（`--n-cpu-moe`）无意义，保持 `--cpu-moe` 全卸载；`-t 16` 无提升（38.6 ≈ 39.2）；官方参数：思考 0.6/0.95、非思考 0.2/top_k 1（bench 用关思考 0.6） |

要点：
- 两款均为 Strata 式"专家常驻内存 + 激活上 GPU"方案的再次验证：8GB 显存跑 24B/30B MoE，速度 30-44 tok/s。
- LFM2-24B 为非思考模型，官方推荐 temp 0.1-0.3；Nemotron 思考可用 `chat_template_kwargs: {"enable_thinking": false}` 关闭（bench 与 agent 测试均关闭）。
- 局限：lfm24b 纯文本无视觉；nemotron 英文语料为主，中文对话偶发英文作答；两款 T4 长文（pp 阶段）受 CPU 专家卸载拖累，19-26 tok/s。
- bench 结果在 `bench_results\lfm24b\`、`bench_results\nemotron\`（全文留档）；工具调用结果见 `d:\models\tools\storytold-ArtCraft\ai-agent\工具调用测试报告.md`（Nemotron 3/3 全过，LFM2-24B 仅 A 过）。
