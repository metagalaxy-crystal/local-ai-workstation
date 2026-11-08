#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strata 云端多模态示例：本地图片 base64 上传 + 图片提问。

默认使用 bench T6 测试同一张蒸汽朋克场景图，可用 --image 换图：
  python example_vision.py --image D:\\path\\to\\your.png
"""
import argparse

from strata_client import chat, image_content

DEFAULT_IMAGE = (r"D:\models\sample\铁锈海的女儿"
                 r"\08_image_pipeline\outputs"
                 r"\zimage_t2i_710895999_zimage_t2i_00001_.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=DEFAULT_IMAGE, help="本地图片路径")
    ap.add_argument("--ask", default="详细描述这张图片：场景内容、人物（如有）、构图、色调氛围。")
    args = ap.parse_args()

    messages = [{"role": "user", "content": image_content(args.ask, args.image)}]
    text, usage, dt = chat(messages, max_tokens=1024)
    print(text)
    print(f"-- 耗时 {dt:.1f}s | 输入 {usage.get('prompt_tokens', 0)} tok | "
          f"输出 {usage.get('completion_tokens', 0)} tok")


if __name__ == "__main__":
    main()
