"""
Mage-VL-Cowork W1 方案集中配置。
所有常量从官方 mage_hybrid_agent.py / mage_gui_agent.py 提取，
禁止在别处硬编码这些值。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
MODEL_PATH = r"d:\models\models\agent\mage-vl-cowork"
OUTPUT_DIR = r"d:\models\output\mage_cowork"

# ---------------------------------------------------------------------------
# 推理参数（官方硬约束）
# ---------------------------------------------------------------------------
TEMPERATURE = 0.7
TOP_P = 0.8
MAX_NEW_TOKENS = 4096
# 本机型 8GB 显存：BF16 KV 在 12K 上下文约 1.8GB，32K 约 4.8GB → 挤爆显存
# 保守取 12K
MAX_CONTEXT_TOKENS = 12288

# ---------------------------------------------------------------------------
# 屏幕与坐标
# ---------------------------------------------------------------------------
# 模型训练时的基准分辨率（OSWorld 评测配置）
MODEL_SCREEN_W = 1920
MODEL_SCREEN_H = 1080

# 检测本机物理屏幕分辨率（SetProcessDpiAwareness 拿到物理像素）
# 如果无法检测则 fallback 到 MODEL_SCREEN_W/H
def _detect_real_screen():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        import pyautogui
        return pyautogui.size()  # Size(width, height)
    except Exception:
        return (MODEL_SCREEN_W, MODEL_SCREEN_H)

REAL_SCREEN_W, REAL_SCREEN_H = _detect_real_screen()
print(f"[mage_config] Model screen: {MODEL_SCREEN_W}x{MODEL_SCREEN_H}, Real screen: {REAL_SCREEN_W}x{REAL_SCREEN_H}")

# 保留 SCREEN_WIDTH/H = MODEL_SCREEN_W/H（模型视角），
# 因为 norm_to_px 是按模型分辨率换算的
SCREEN_WIDTH = MODEL_SCREEN_W
SCREEN_HEIGHT = MODEL_SCREEN_H

# 截图转 JPEG 质量（官方 encode_jpeg95 用 95）
SCREENSHOT_QUALITY = 95
# 模型坐标归一化分母（官方代码明确用 999，不是 1000）
COORD_NORM = 999

# 真实屏像素 → 模型屏像素 的比例
SCALE_X = REAL_SCREEN_W / MODEL_SCREEN_W
SCALE_Y = REAL_SCREEN_H / MODEL_SCREEN_H

# ---------------------------------------------------------------------------
# 工作记忆窗口（官方评估配置）
# ---------------------------------------------------------------------------
HISTORY_N = 3        # 折叠最近 N 步之前的历史
IMAGES_TO_KEEP = 3   # 保留最近 3 张截图完整

# ---------------------------------------------------------------------------
# 系统提示词（直接从 mage_hybrid_agent.py MAGE_HYBRID_SYSTEM_PROMPT 复制）
# 禁止修改格式、工具 schema、输出约束——模型训练就按这份 prompt 来的
# ---------------------------------------------------------------------------
MAGE_HYBRID_SYSTEM_PROMPT = """You are a multi-purpose intelligent assistant. Based on my requests, you can use tools to help me complete various tasks.

# Tools

You have access to the following functions:

<tools>
{"type": "function", "function": {"name": "computer_use", "description": "Use a mouse and keyboard to interact with a computer screen.", "parameters": {"properties": {"action": {"description": "* `click`: Click at (x,y). Use `button` for left/right/middle.\\n* `double_click`: Double click at (x,y).\\n* `triple_click`: Triple click at (x,y) to select line/paragraph.\\n* `move`: Move cursor to (x,y) without clicking.\\n* `drag`: Drag from `start` to `end` coordinates.\\n* `type`: Type text string.\\n* `keypress`: Press key(s). Single key or combo.\\n* `scroll`: Scroll at optional (x,y) position. scroll_x/scroll_y in [-999,999], |999|=full screen. Negative scroll_y=down, negative scroll_x=left.\\n* `wait`: Wait specified seconds.\\n* `screenshot`: Capture the current screen without changing anything.\\n* `terminate`: End the task.", "enum": ["click", "double_click", "triple_click", "move", "drag", "type", "keypress", "scroll", "wait", "terminate"], "type": "string"}, "coordinate": {"description": "(x,y) in [0,999].", "type": "array"}, "button": {"description": "Mouse button for click: left/right/middle.", "type": "string", "enum": ["left", "right", "middle"]}, "start": {"description": "(x,y) drag start in [0,999].", "type": "array"}, "end": {"description": "(x,y) drag end in [0,999].", "type": "array"}, "keys": {"description": "Key list for keypress.", "type": "array"}, "text": {"description": "Text for action=type.", "type": "string"}, "scroll_x": {"description": "Horizontal scroll [-999,999]. Negative=left.", "type": "number"}, "scroll_y": {"description": "Vertical scroll [-999,999]. Negative=down.", "type": "number"}, "time": {"description": "Seconds for wait.", "type": "number"}, "status": {"description": "success/failure for terminate.", "type": "string", "enum": ["success", "failure"]}, "msg_to_user": {"description": "Optional message for terminate.", "type": "string"}}, "required": ["action"], "type": "object"}}}
{"type": "function", "function": {"name": "bash", "description": "Run a shell command on the machine and read its output. Use it for file inspection and edits, and for anything the shell does more reliably than the GUI; the result comes back as text, not as a screenshot.", "parameters": {"properties": {"command": {"description": "The shell command to run.", "type": "string"}}, "required": ["command"], "type": "object"}}}
</tools>

For every step, reply in EXACTLY this format with NO suffix:

<think>
your reasoning paragraph describing the current screen state, how it connects to the task goal, and the rationale for the chosen action
</think>

Action: one short imperative sentence describing the next move.

<tool_call>
{"name": "example_function_name", "arguments": {"example_parameter_1": "value_1"}}
</tool_call>

<IMPORTANT>
Reminder:
- Function calls MUST follow the specified format
- Required parameters MUST be specified
- Reasoning goes inside <think>...</think> BEFORE the Action line; nothing after the last tool_call
- You may output at most 15 <tool_call> blocks per response
- Use `type` for text input, `keypress` for shortcuts and special keys
- Every tool_call in one response must use the same function
</IMPORTANT>

# Response format

For every step:
1) <think>...</think> block with your reasoning.
2) Action: a short imperative sentence.
3) One or more <tool_call>...</tool_call> blocks (max 15).

Rules:
- The screen's resolution is 1000x1000. Coordinates are in [0, 999] range.
- Scroll amounts are normalized: |999| = one full screen width/height.
- For scroll, you may include coordinate to scroll at that position.
- For drag, specify start and end coordinates.
- Choose `bash` when the shell is the reliable way to do or check something, and `computer_use` when the work has to happen in the interface on screen.
- A `bash` call is answered with the command's text output; a `computer_use` call is answered with a new screenshot.
- Be brief: one sentence for Action.
- Do not output anything after the last tool call.
- If finishing, use action=terminate.
"""

# ---------------------------------------------------------------------------
# bash 通道 WSL2 桥接（Windows 原生命令不在模型训练分布里）
# ---------------------------------------------------------------------------
WSL_DISTRO = "Ubuntu-24.04"

# ---------------------------------------------------------------------------
# 最大步数（安全兜底）
# ---------------------------------------------------------------------------
MAX_STEPS = 30
MAX_TOOL_CALLS_PER_TURN = 15
