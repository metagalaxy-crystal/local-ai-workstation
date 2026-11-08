# -*- coding: utf-8 -*-
"""P2b 生成与语音工具单测：注册、参数构造、产物解析（子进程全部 mock）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.config import Config
from agent.tools import build_registry, comfy, scope, voice
from agent.tools.proc import ProcResult


def make_cfg(root: Path, enabled=("comfy", "voice")) -> Config:
    return Config({
        "tools": {
            "enabled": list(enabled),
            "tool_timeout": 20, "retry": 0,
            "allowed_roots": [str(root)],
            "scripts_dir": str(root / "scripts"),
            "shell_whitelist": [], "blocked_patterns": [],
            "search": {"provider": "duckduckgo", "max_results": 5},
            "browser": {"headless": True},
            "comfy": {"host": "http://127.0.0.1:8188", "image_timeout": 120,
                      "video_timeout": 240, "music_timeout": 180},
            "voice": {"tts_timeout": 90, "asr_timeout": 120},
        },
        "rag": {"embed_url": "http://127.0.0.1:1/v1",
                "rerank_url": "http://127.0.0.1:1/rerank",
                "chunk_size": 120, "chunk_overlap": 30, "top_k": 3, "recall_candidates": 10},
        "paths": {"workspace": str(root / "ws"), "db": str(root / "s.db"),
                  "vectors_db": str(root / "v.db"), "output_root": str(root / "out")},
    }, Path("test-config"))


class BaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cfg = make_cfg(self.root)
        scope.configure(self.cfg)
        comfy.configure(self.cfg)
        voice.configure(self.cfg)
        # 脚本只要存在即可（不会真正执行）
        for name in ("comfyui/run_image.py", "comfyui/run_video.py",
                     "comfyui/run_music.py", "other/tts_moss.py", "other/asr_diarize.py"):
            path = self.root / "scripts" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class RegistryTests(BaseCase):
    def test_families_registered(self) -> None:
        reg = build_registry(self.cfg)
        for expected in ("comfy_status", "generate_image", "generate_video",
                         "generate_music", "tts_speak", "asr_transcribe"):
            self.assertIn(expected, reg.names())

    def test_schema_and_timeout(self) -> None:
        reg = build_registry(self.cfg)
        specs = {s.name: s for s in reg._specs.values()}
        self.assertEqual(specs["generate_video"].timeout, 240)
        schema = specs["generate_image"].parameters
        self.assertEqual(schema["required"], ["prompt"])
        self.assertIn("anima", schema["properties"]["model"]["enum"])


class ComfyTests(BaseCase):
    def _run_stub(self, artifact: Path):
        def fake(command, **kwargs):
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"\x89PNG")
            return ProcResult(0, f"# 产物：{artifact}（1.2KB）\n", "")
        return fake

    def test_image_down(self) -> None:
        with patch.object(comfy, "_up", return_value=False), \
             patch.object(comfy, "run_process") as run:
            out = comfy.generate_image("一只猫")
        self.assertIn("未启动", out)
        run.assert_not_called()

    def test_image_args_and_artifact(self) -> None:
        png = self.root / "out" / "a.png"
        with patch.object(comfy, "_up", return_value=True), \
             patch.object(comfy, "_port_open", return_value=False), \
             patch.object(comfy, "run_process", side_effect=self._run_stub(png)) as run:
            out = comfy.generate_image("一只猫", model="ernie", steps=8,
                                       res="1024x1024", seed=7)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("ernie", cmd)
        for flag, value in (("--steps", "8"), ("--res", "1024x1024"), ("--seed", "7")):
            self.assertEqual(cmd[cmd.index(flag) + 1], value)
        self.assertIn("生成完成", out)
        self.assertIn(str(png), out)

    def test_video_rejects_outside_path(self) -> None:
        with patch.object(comfy, "_up", return_value=True):
            out = comfy.generate_video("推进", first_frame="C:/Windows/notallowed.png")
        self.assertIn("路径不可用", out)

    def test_video_args(self) -> None:
        mp4 = self.root / "out" / "v.mp4"
        with patch.object(comfy, "_up", return_value=True), \
             patch.object(comfy, "_port_open", return_value=False), \
             patch.object(comfy, "run_process", side_effect=self._run_stub(mp4)) as run:
            out = comfy.generate_video("镜头推进", length=73, fps=24)
        cmd = run.call_args.args[0]
        self.assertIn("run_video.py", " ".join(cmd))
        self.assertEqual(cmd[cmd.index("--length") + 1], "73")
        self.assertIn(str(mp4), out)

    def test_music_args(self) -> None:
        mp3 = self.root / "out" / "m.mp3"
        with patch.object(comfy, "_up", return_value=True), \
             patch.object(comfy, "_port_open", return_value=False), \
             patch.object(comfy, "run_process", side_effect=self._run_stub(mp3)) as run:
            out = comfy.generate_music("ambient, piano", duration=20, fmt="wav")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--duration") + 1], "20")
        self.assertEqual(cmd[cmd.index("--format") + 1], "wav")
        self.assertIn(str(mp3), out)

    def test_failure_reports_stderr(self) -> None:
        with patch.object(comfy, "_up", return_value=True), \
             patch.object(comfy, "_port_open", return_value=False), \
             patch.object(comfy, "run_process",
                          return_value=ProcResult(1, "", "[FAIL] 模型名找不到")):
            out = comfy.generate_image("x")
        self.assertIn("文生图失败", out)
        self.assertIn("模型名找不到", out)

    def test_status_down(self) -> None:
        with patch.object(comfy, "_up", return_value=False):
            self.assertIn("未启动", comfy.comfy_status())


class VoiceTests(BaseCase):
    def test_tts_with_ref(self) -> None:
        ref = self.root / "ref.wav"
        ref.write_bytes(b"RIFF")

        def fake(command, **kwargs):
            out = Path(command[command.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"RIFF" + b"\x00" * 64)
            return ProcResult(0, f"完成: {out}  (1.20s)", "")

        with patch.object(voice, "_port_open", return_value=False), \
             patch.object(voice, "run_process", side_effect=fake) as run:
            out = voice.tts_speak("你好", ref_audio=str(ref))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--ref-audio") + 1], str(ref))
        self.assertIn("语音已合成", out)
        self.assertIn(".wav", out)

    def test_tts_rejects_missing_ref(self) -> None:
        out = voice.tts_speak("你好", ref_audio=str(self.root / "nope.wav"))
        self.assertIn("参考音频不存在", out)

    def test_asr_reads_json(self) -> None:
        audio = self.root / "talk.wav"
        audio.write_bytes(b"RIFF")

        def fake(command, **kwargs):
            source = Path(command[4])
            out_dir = Path(command[command.index("--out-dir") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{source.stem}.json").write_text(json.dumps([
                {"start": 0.0, "end": 2.5, "text": "你好", "speaker": "SPEAKER_00"},
                {"start": 2.6, "end": 4.0, "text": "在的", "speaker": "SPEAKER_01"},
            ], ensure_ascii=False), encoding="utf-8")
            (out_dir / f"{source.stem}.srt").write_text("1\n", encoding="utf-8")
            return ProcResult(0, "[OK] JSON", "")

        with patch.object(voice, "_port_open", return_value=False), \
             patch.object(voice, "run_process", side_effect=fake) as run:
            out = voice.asr_transcribe(str(audio), speakers=2, align=True)
        cmd = run.call_args.args[0]
        self.assertIn("--align", cmd)
        self.assertEqual(cmd[cmd.index("--speakers") + 1], "2")
        self.assertIn("SPEAKER_00", out)
        self.assertIn("字幕", out)
        self.assertIn("在的", out)


if __name__ == "__main__":
    unittest.main()
