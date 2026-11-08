# 《铁锈海的女儿》模型链路实施记录

> 本文档记录本案例调用 `d:\models\models\` 模型库的**具体实施方案**（脚本、命令、产物）。
> 通用的任务-模型链路说明见模型库根目录 `d:\models\models\README.md` 第二部分。

## 生产链路总览

```
分镜脚本 ──► 文生图 ──► 图生视频 ──► BGM 生成 ──► 音乐质检 ──► 对白 TTS ──► 转写/分离/字幕 ──► 成片合成
```

| 环节 | 模型 | 平台 | 本项目调用方 |
|---|---|---|---|
| ① 分镜脚本 | LFM2.5（路由 `lfm`）/ Nanbeige（路由 `nanbeige`）本地 llama-server；**云端 Strata（路由 `strata`，Qwen3.8-Flash-Next 176B，质量档首选）**；deepseek、qwen35b、trae_glm5 走在线 API | llama.cpp :8081；Strata `10.203.239.162:8082` | `03_storyboard\llm_runner.py`（strata 用法：`strata 8082 --host 10.203.239.162 --key <key> --effort low`，key 见 `d:\models\docs\strata\API密钥管理方案.md`）；`scripts\start_llm_server.py`、`start_llm_nanbeige.bat/.ps1`；一键 bat 在 `d:\models\scripts\run-*.bat`；对比实测 `06_compare\llm_bench.md` 第 6 节 |
| ② 文生图 | Z-Image（主力）/ ERNIE（文字渲染）/ Anima（二次元） | ComfyUI | `08_image_pipeline\gen_image.py --workflow workflow_{zimage\|anima\|ernie}_t2i_api.json`；实测记录见 `02_design\design.md` 第 9 节 |
| ③ 图生视频 | MiniMax-H3 int8 + Qwen3-VL-32B 编码器 + 双 VAE | ComfyUI（独占 ≈8GB） | `scripts\batch_submit.py --model minimax_h3 --unet_name "MiniMax-H3\diffusion_models\minimax_h3_fl2va_pruned_int8_convrot.safetensors" --prefix minimax_int8`、`scripts\submit_minimax_h3.py`；产物在 `05_minimax_h3\` |
| ④ BGM 生成 | ACE-Step-1.5（qwen_1.7b 编码器） | ComfyUI | `scripts\submit_bgm.py` + `scripts\workflow_acestep_bgm_api.json`（API 中模型名用反斜杠且不带 music/ 前缀）；产物示例：`bgm_steampunk_00001.flac`（19s 蒸汽朋克） |
| ⑤ 音乐质检 | MOSS-Music-8B（bitsandbytes 4bit） | python .venv（独占 ≈6GB，与 ComfyUI 互斥） | `scripts\analyze_music.py`；主判据：调性/配器/情绪/时长 |
| ⑥ 对白 TTS | MOSS-TTS + MOSS-Audio-Tokenizer | python .venv | `scripts\gen_speech.py`（角色台词）、`scripts\make_voice_refs.py`（变调派生父/女参考音色）；产物在 `06_compare\speech\` |
| ⑦ 转写 + 分离 + 字幕 | silero-vad → Qwen3-ASR-0.6B → campplus+KMeans → [--align] ForcedAligner | python .venv | `scripts\diarize_transcribe_funasr.py <音频> --align --speakers 2 --srt out.srt --json out.json` |
| ⑧ 成片合成 | 视频帧 + BGM + 对白 + 字幕混流 | python .venv | `scripts\concat_shots.py`、`concat_mix.py` |

## 运行环境

- ComfyUI 启动：`d:\models\scripts\start-comfyui.bat` / `start_comfyui.py`；模型库经 `extra_model_paths.yaml` 挂载
- llama-server：`d:\models\llama.cpp\build\bin\Release\llama-server.exe`（OpenAI 兼容 :8081）
- python 环境：`d:\models\.venv`（FunASR 1.4.16 / qwen-asr / transformers 4.57.6 / torch 2.14.0+cu130）

## 操作纪律

1. **显存互斥**：ComfyUI（≈8GB）与 MOSS-Music（≈6GB）不可同时运行，音乐质检前必须先停 ComfyUI 进程
2. 音频生成、人声生成、所有测试报告、脚本、分镜、最终成片**永久保留，不得删除**
3. 视频生成仅保留 MiniMax-H3 int8 链路（Wan2.2 全链路已清理，恢复按 `scripts\download_int8_pruned.py` 重下）

## 辅助脚本（`scripts\` 目录）

`wait_all_done.py` / `wait_batch.py` / `collect_timebook.py`（批量任务等待与计时账簿）、`clear_queue.py`（清 ComfyUI 队列）、`smoke_test.py`（冒烟测试）、`extract_frames.py`（抽帧）、`transcribe_voice.py`、`diarize_transcribe.py`（sherpa-onnx 路线，已作废留档）、`analyze_music.py`、`test_forced_aligner.py`（对齐器独立验证）

## 目录索引

| 目录 | 内容 |
|---|---|
| `01_story_text\` | 故事文本 |
| `02_design\` | 方案设计（design.md 含各模型实测记录） |
| `03_storyboard\` | 分镜脚本（LLM 生成） |
| `04_wan22\` | Wan2.2 历史产物（留档） |
| `05_minimax_h3\` | H3 视频镜头产物 |
| `06_compare\` | 对比评测（llm_bench.md、timebook_all.md）、speech\ 人声 |
| `07_reports\` | 报告汇总（summary.md） |
| `08_image_pipeline\` | 文生图工作流与产物 |
