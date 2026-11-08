"""
Mage-VL-Cowork W1 本地 4bit 推理层。
Transformers + bitsandbytes NF4，8GB 显存可跑。

用法:
    from mage_infer import MageLocalInference
    infer = MageLocalInference()
    infer.load()
    response = infer.step(instruction="点击深色模式开关", screenshot_path="shot.jpg")
    print(infer.extract_tool_calls(response))
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import torch
from PIL import Image

from mage_config import (
    MAGE_HYBRID_SYSTEM_PROMPT,
    MAX_NEW_TOKENS,
    MODEL_PATH,
    TEMPERATURE,
    TOP_P,
)

logger = logging.getLogger("mage.infer")

# ---------------------------------------------------------------------------
# bitsandbytes 4bit NF4 配置（8GB 显存最优档）
# ---------------------------------------------------------------------------
_BNB_CONFIG_DICT = {
    "load_in_4bit": True,
    "bnb_4bit_quant_type": "nf4",
    "bnb_4bit_compute_dtype": "bfloat16",
    "bnb_4bit_use_double_quant": False,
}


# ---------------------------------------------------------------------------
# 图像编码
# ---------------------------------------------------------------------------
def screenshot_to_data_uri(image_bytes: bytes | Image.Image, quality: int = 95) -> str:
    """PIL Image 或 raw bytes → data:image/jpeg;base64,..."""
    if isinstance(image_bytes, (bytes, bytearray)):
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    elif isinstance(image_bytes, Image.Image):
        img = image_bytes.convert("RGB")
    else:
        raise TypeError(f"Unsupported image input: {type(image_bytes)}")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


# ---------------------------------------------------------------------------
# 输出解析
# ---------------------------------------------------------------------------
_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>",
)
_ACTION_LINE_RE = re.compile(r"Action:\s*(.+?)(?:\n|$)")
_THINK_RE = re.compile(r"<think>\s*([\s\S]*?)\s*</think>")


def parse_response(response: str) -> dict[str, Any]:
    """
    解析 Mage 三段式输出，返回:
    {
        "think": "...",
        "action": "一句话摘要",
        "tool_calls": [{"name": "computer_use", "arguments": {...}}, ...]
    }
    """
    think_match = _THINK_RE.search(response)
    think = think_match.group(1).strip() if think_match else ""

    action_match = _ACTION_LINE_RE.search(response)
    action = action_match.group(1).strip() if action_match else ""

    tool_calls: list[dict[str, Any]] = []
    for m in _TOOL_CALL_RE.finditer(response):
        try:
            tool_calls.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            logger.warning("Failed to parse tool_call JSON: %s", m.group(1)[:200])

    return {"think": think, "action": action, "tool_calls": tool_calls}


# ---------------------------------------------------------------------------
# 推理类
# ---------------------------------------------------------------------------
@dataclass
class MageLocalInference:
    """本地 4bit NF4 推理封装。"""

    model_path: str = MODEL_PATH
    system_prompt: str = MAGE_HYBRID_SYSTEM_PROMPT
    temperature: float = TEMPERATURE
    top_p: float = TOP_P
    max_new_tokens: int = MAX_NEW_TOKENS

    # 内部状态（load 之后填充）
    _processor: Any = field(default=None, repr=False)
    _model: Any = field(default=None, repr=False)
    _bnb_config: Any = field(default=None, repr=False)
    _loaded: bool = False

    # 对话历史（messages 格式，每轮 user/assistant/tool 交替）
    _messages: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def load(self) -> None:
        """加载 processor + 4bit NF4 模型。首次调用最重，约 1-3 分钟。"""
        if self._loaded:
            return
        from transformers import AutoModelForCausalLM, AutoProcessor, BitsAndBytesConfig

        logger.info("Loading processor from %s ...", self.model_path)
        self._processor = AutoProcessor.from_pretrained(
            self.model_path, trust_remote_code=True
        )

        logger.info("Loading model (4bit NF4) from %s ...", self.model_path)
        self._bnb_config = BitsAndBytesConfig(**_BNB_CONFIG_DICT)
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            trust_remote_code=True,
            device_map="auto",
            quantization_config=self._bnb_config,
            torch_dtype=torch.bfloat16,
        )
        self._model.eval()
        self._loaded = True
        logger.info("Model loaded. Device: %s, dtype: %s",
                    next(self._model.parameters()).device, next(self._model.parameters()).dtype)

    # ---------------------------------------------------------------
    # 消息构造（与官方 _build_messages 对齐，简化版——每轮全量重建）
    # ---------------------------------------------------------------
    def _make_messages(self, instruction: str, prev_actions: str) -> list[dict[str, Any]]:
        """按官方 README 的写法：content 里放 {"type":"image"} 占位 + 文本，图片单独传。"""
        return [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {
                        "type": "text",
                        "text": (
                            f"Please generate the next move according to the UI screenshot, "
                            f"instruction and previous actions.\n\n"
                            f"Instruction: {instruction}\n\n"
                            f"Previous actions:\n{prev_actions}"
                        ),
                    },
                ],
            },
        ]

    # ---------------------------------------------------------------
    # 单步推理
    # ---------------------------------------------------------------
    @torch.inference_mode()
    def generate(self, messages: list[dict[str, Any]], images: list[Image.Image]) -> str:
        """messages + N 张截图 → apply_chat_template → processor → generate → decode。"""
        if not self._loaded:
            raise RuntimeError("Call .load() first")

        prompt = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._processor(text=[prompt], images=images, return_tensors="pt")
        # 新版 Qwen2.5-VL processor 会多吐 mm_token_type_ids，模型 forward 不接收
        inputs.pop("mm_token_type_ids", None)
        device = next(self._model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}
        if "pixel_values" in inputs:
            inputs["pixel_values"] = inputs["pixel_values"].to(self._model.dtype)

        # 模型视觉侧强制需要 patch_positions（README 示例未传，官方主推 SGLang 路径）
        # 每张图按 Qwen2-VL 的 (t,h,w) 行主序展开，多图按顺序拼起来
        grid = inputs.get("image_grid_thw")
        if grid is not None and "patch_positions" not in inputs:
            chunks = []
            for row in grid.tolist():
                gt, gh, gw = (int(x) for x in row)
                chunks.append(
                    torch.cartesian_prod(
                        torch.arange(gt, device=device),
                        torch.arange(gh, device=device),
                        torch.arange(gw, device=device),
                    )
                )
            coords = torch.cat(chunks, dim=0)
            inputs["patch_positions"] = coords.unsqueeze(0).long()
            logger.info(
                "patch_positions: %s -> %d patches",
                [tuple(int(x) for x in r) for r in grid.tolist()],
                coords.shape[0],
            )

        logger.info("Input tokens: %d", inputs["input_ids"].shape[-1])

        outputs = self._model.generate(
            **inputs,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            do_sample=True,
        )

        new_tokens = outputs[0, inputs["input_ids"].shape[-1]:]
        text = self._processor.tokenizer.decode(new_tokens, skip_special_tokens=True)
        return text.strip()

    # ---------------------------------------------------------------
    # 便捷入口：一张截图 + 指令 → 解析后的响应
    # ---------------------------------------------------------------
    def step(
        self,
        instruction: str,
        screenshot_image: Image.Image | bytes,
        prev_action_summary: str = "None",
    ) -> dict[str, Any]:
        """执行一步推理。返回 parse_response 字典 + 原始 response。"""
        if isinstance(screenshot_image, (bytes, bytearray)):
            screenshot_image = Image.open(io.BytesIO(screenshot_image)).convert("RGB")
        messages = self._make_messages(instruction, prev_action_summary)
        raw = self.generate(messages, [screenshot_image])
        parsed = parse_response(raw)
        parsed["_raw"] = raw
        return parsed


# ---------------------------------------------------------------------------
# 独立测试入口：python mage_infer.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    import sys

    infer = MageLocalInference()
    infer.load()

    # 测试：用一张纯色占位图，验证推理链路通
    dummy = Image.new("RGB", (1920, 1080), (30, 30, 30))
    resp = infer.step(
        instruction="Please click on the Start menu button in the bottom left corner of the screen.",
        screenshot_image=dummy,
    )
    print("\n=== Model Raw Output ===")
    print(resp["_raw"])
    print("\n=== Parsed ===")
    print(json.dumps(resp, indent=2, ensure_ascii=False))
