# -*- coding: utf-8 -*-
"""项目入口包：本地 Agent 的极薄 tool-call 循环实现。

模块划分：
    config   配置读取（configs/agent.json，可用 AGENT_CONFIG 覆盖）
    llm      llama-server 的 OpenAI 兼容客户端
    router   按用途选择模型（主脑 / 轻任务 / 视觉）
    context  历史裁剪
    loop     主循环 + 护栏
    cli      交互式命令行
"""
