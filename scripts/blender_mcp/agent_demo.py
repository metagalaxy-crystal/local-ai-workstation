"""大模型 → MCP → Blender 全链路样例。

流程：
  用户一句话需求
    → 本地大模型（llama-server，OpenAI 兼容 /v1/chat/completions）理解并写出 bpy 建模代码
    → 模型通过正式 tool_call 调用 MCP 工具 execute_blender_code
    → Blender 执行代码建出场景
    → MCP 工具 render_viewport_to_path 出图
    → 大模型落盘 .blend + PNG，并把生成的代码存档便于复现

用法：
    python d:\\models\\scripts\\blender_mcp\\agent_demo.py
    python ...\\agent_demo.py --prompt "生成一只坐在月亮上的橘猫"
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_demo import MCPClient, MCP_EXE, bridge_alive, start_bridge  # noqa: E402

OUTPUT_DIR = r"d:\models\output\blender_mcp"
DEFAULT_PROMPT = (
    "在 Blender 里程序化生成一只「火花猫」：深炭色的猫身，眼睛发出青绿色光，"
    "周身环绕漂浮的橙金色火花，暗色背景，整体像一张风格化的角色概念图。"
)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8080/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen36")

SYSTEM_PROMPT = """你是资深 Blender 技术美术，通过 MCP 工具在 Blender 5.1 里用 bpy 程序化建模。

规则：
1. 每次只发一次工具调用 execute_blender_code，code 是完整可独立运行的 Python（bpy 已可用）。
2. 场景从空开始：脚本第一段先删除所有对象（bpy.data.objects.remove(obj, do_unlink=True)）。
3. 只用内置几何体（primitive_uv_sphere_add / cone_add / cylinder_add / plane_add 等），不要引用外部贴图或文件。
4. 坐标 Z 轴向上，单位米；角色整体高度 2~3 米，相机放在 (3~5, -6, 3) 附近看向角色胸口高度。
5. 材质用 Principled BSDF：颜色写 inputs["Base Color"]，自发光写 inputs["Emission Color"] 与 inputs["Emission Strength"]。
6. 需要辉光时不要碰合成器（Blender 5.x 合成器 API 改动较大），改用高强度自发光材质 + 灯光来营造。
7. 不要调用渲染、不要保存文件、不要操作 UI（bpy.ops.render / wm.save_as_mainfile / wm.open_mainfile 全部禁止），出图与存档由外部脚本负责。
8. 结束后把一句话设计说明写进 result 字典（result = {"design": "..."}），便于日志查看。
9. 若工具返回 traceback，读懂报错后修正代码，再次调用同一工具。不要重复提交完全相同的代码。
10. 代码控制在 80 行以内，不要写大段注释与说明文字；注释只允许极短的中文行内说明。

画面要求：风格化、有明确轮廓、主体占画面 60% 以上、暗背景高对比。

参考造型（可直接采用，猫面朝 -Y，相机在 -Y 一侧）：
- 身体：椭球，中心 (0, 0, 1.0)，半径 1.0，缩放 (0.95, 0.85, 1.05)
- 头：球体，中心 (0, -0.15, 2.05)，半径 0.6，缩放 (1.0, 0.95, 0.92)
- 耳朵：两个圆锥，尖端朝上，位于头两侧 z≈2.5，半径 0.24、高 0.45
- 眼睛：两个球体，必须位于头部 -Y 表面之外（y ≈ -0.62，x ≈ ±0.24，z ≈ 2.15），半径 0.13，自发光强度 6~10，否则会被头挡住
- 鼻子：小椭球在 (0, -0.72, 1.95)
- 四腿：4 根圆柱，半径 0.13、高 0.7，贴近地面
- 尾巴：一串半径从 0.28 递减到 0.10 的球体，从身体后侧 (+Y) 向上卷起
- 火花：60~90 个半径 0.02~0.07 的发光小球，分布在猫身周围 0.8~1.6 米的球壳内
- 地面：一块深色平面；不要给猫加条纹、斑点等贴图花纹
"""


def _post_stream(url, payload, timeout=600):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json", "Authorization": "Bearer local",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def _post_stream_retry(url, payload):
    """本地服务偶发 500 / 连接抖动时重试一次，并打印服务端返回的错误体。"""
    try:
        return _post_stream(url, payload)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "ignore")[:600]
        print("\n[llm] HTTP %s: %s（2 秒后重试一次）" % (err.code, body))
        time.sleep(2)
        try:
            return _post_stream(url, payload)
        except urllib.error.HTTPError as err2:
            raise SystemExit("[llm] 重试仍失败 HTTP %s: %s" %
                             (err2.code, err2.read().decode("utf-8", "ignore")[:600]))
    except ( urllib.error.URLError, TimeoutError) as err:
        print("\n[llm] 连接失败：%s（2 秒后重试一次）" % err)
        time.sleep(2)
        return _post_stream(url, payload)


def chat_stream(messages, tools):
    """流式请求本地大模型，边打印边累积 tool_calls。返回 (content, tool_calls, usage)。"""
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.6,
        "top_p": 0.85,
        "max_tokens": 3072,
        "stream": True,
        "stream_options": {"include_usage": True},
        # 关掉思考链：本地 35B 在工具调用场景下思考链会挤占输出预算，导致代码被截断。
        "chat_template_kwargs": {"enable_thinking": False},
    }
    content, reasoning = [], []
    calls, usage, finish = {}, {}, ""
    resp = _post_stream_retry(LLM_BASE_URL + "/chat/completions", payload)
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            obj = json.loads(chunk)
            if obj.get("usage"):
                usage = obj["usage"]
            for choice in obj.get("choices") or []:
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                delta = choice.get("delta") or {}
                if delta.get("reasoning_content"):
                    reasoning.append(delta["reasoning_content"])
                    sys.stdout.write(delta["reasoning_content"])
                    sys.stdout.flush()
                if delta.get("content"):
                    content.append(delta["content"])
                    sys.stdout.write(delta["content"])
                    sys.stdout.flush()
                for tc in delta.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", 0), {
                        "id": "", "type": "function",
                        "function": {"name": "", "arguments": ""},
                    })
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]
    return "".join(content), reasoning, [calls[k] for k in sorted(calls)], usage, finish


def to_openai_tools(mcp_tools, allow):
    out = []
    for t in mcp_tools:
        if t["name"] not in allow:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": (t.get("description") or "")[:400],
                "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
            },
        })
    return out


def extract_code(text):
    """模型把代码写在正文而非 tool_call 时，从 ```python 代码块里捞出来。"""
    match = re.search(r"```(?:python|py)?\s*(.*?)```", text or "", re.S)
    return match.group(1).strip() if match else None


def call_tool(client, name, arguments):
    started = time.time()
    payload = client.call_tool(name, arguments)
    structured = payload.get("structuredContent") or {}
    text = payload["content"][0]["text"] if payload.get("content") else ""
    if structured.get("status") == "error":
        detail = structured.get("message", "")
    else:
        detail = structured.get("result") or structured or text
    print("\n[mcp] %s 用时 %.1fs → %s" % (
        name, time.time() - started, json.dumps(detail, ensure_ascii=False)[:300]))
    return structured, detail


def main():
    parser = argparse.ArgumentParser(description="大模型通过 MCP 生成 Blender 场景")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="给大模型的需求描述")
    parser.add_argument("--max-rounds", type=int, default=6, help="模型-工具交互最大轮数")
    parser.add_argument("--keep-scene", action="store_true", help="保留当前场景，不预先清空")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    png_path = os.path.join(OUTPUT_DIR, "llm_spark_cat.png")
    blend_path = os.path.join(OUTPUT_DIR, "llm_spark_cat.blend")
    code_path = os.path.join(OUTPUT_DIR, "llm_spark_cat_code.py")

    if not bridge_alive():
        start_bridge()

    client = MCPClient(MCP_EXE)
    client.initialize()
    mcp_tools = client.list_tools()
    tools = to_openai_tools(mcp_tools, {"execute_blender_code"})
    print("[demo] MCP 工具 %d 个，已向模型暴露：%s" %
          (len(mcp_tools), ", ".join(t["function"]["name"] for t in tools)))

    if not args.keep_scene:
        client.call_tool("execute_blender_code", {
            "code": "import bpy\nfor o in list(bpy.data.objects):\n    bpy.data.objects.remove(o, do_unlink=True)\nresult = {'cleared': True}",
        })

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": args.prompt},
    ]
    print("\n[demo] 需求：%s\n" % args.prompt)

    generated_codes = []
    final_answer = ""
    try:
        for rnd in range(1, args.max_rounds + 1):
            print("[demo] 第 %d 轮 · 模型生成中 ..." % rnd)
            content, reasoning, calls, usage, finish = chat_stream(messages, tools)
            if content:
                final_answer = content
            if usage:
                print("\n[demo] tokens: prompt=%s completion=%s" %
                      (usage.get("prompt_tokens"), usage.get("completion_tokens")))

            if calls:
                parsed = []
                truncated = False
                for tc in calls:
                    try:
                        arguments = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        truncated = True
                        break
                    parsed.append((tc, arguments))
                if truncated or finish == "length":
                    print("\n[demo] 工具参数在输出上限处被截断，本轮不执行，要求模型压缩代码重试")
                    messages.append({"role": "user", "content":
                                     "上一次工具调用参数在输出长度上限处被截断，未执行。"
                                     "请把 bpy 代码压缩到 80 行以内、删掉大段注释，然后重新调用 execute_blender_code。"})
                    continue
                messages.append({"role": "assistant", "content": content or "",
                                 "tool_calls": calls})
                for tc, arguments in parsed:
                    name = tc["function"]["name"]
                    if name == "execute_blender_code" and arguments.get("code"):
                        generated_codes.append(arguments["code"])
                    structured, detail = call_tool(client, name, arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id") or "call_%d" % rnd,
                        "content": json.dumps(detail, ensure_ascii=False)[:4000],
                    })
                continue

            code = extract_code(content)
            if code:
                generated_codes.append(code)
                structured, detail = call_tool(client, "execute_blender_code", {"code": code})
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content":
                                 "工具执行结果：%s" % json.dumps(detail, ensure_ascii=False)[:2000]})
                continue

            print("\n[demo] 模型结束作答。")
            break
    finally:
        pass

    if generated_codes:
        with open(code_path, "w", encoding="utf-8") as fh:
            fh.write("# 由 %s 生成（%s）\n\n" % (LLM_MODEL, time.strftime("%Y-%m-%d %H:%M:%S")))
            fh.write("\n\n# ---- 下一次生成 ----\n\n".join(generated_codes))
        print("[demo] 生成代码已存档：%s" % code_path)

    print("\n[demo] 收尾：统一渲染设置 + 自动取景 + 出图 + 存工程")
    with open(os.path.join(HERE, "finalize_scene.py"), encoding="utf-8") as fh:
        setup = fh.read().replace("__BLEND_PATH__", blend_path).replace("__PNG_PATH__", png_path)
    client.call_tool("execute_blender_code", {"code": setup})
    # 该工具把图写到 Blender 的 scratch 目录（tempdir/blender_mcp），需要取回路径再拷贝。
    _, rendered = call_tool(client, "render_viewport_to_path", {"output_path": png_path})
    src = rendered.get("filepath") if isinstance(rendered, dict) else None
    if src and os.path.exists(src):
        shutil.copy2(src, png_path)
        print("[demo] 渲染文件已取回：%s" % src)
    client.close()

    print("[demo] 产物：%s" % png_path)
    print("[demo] 工程：%s" % blend_path)
    if final_answer:
        print("[demo] 模型说明：%s" % final_answer.strip()[:300])


if __name__ == "__main__":
    main()
