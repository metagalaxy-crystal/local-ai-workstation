#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从番外小说《铁锈海的女儿》docx 中提取第一节正文。

第一节是文档里第一个数字章节标题「一」到「二」之前的段落。
"""
from pathlib import Path
from docx import Document

SRC = Path(r"D:\models\故事\番外小说 铁锈海的女儿.docx")
DST = Path(r"D:\models\sample\铁锈海的女儿\01_story_text\section1.txt")
SECTIONS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
            "十一", "十二", "十三", "十四", "十五"]


def main() -> int:
    doc = Document(SRC)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    # 找第一节起点
    try:
        start = paragraphs.index("一")
    except ValueError:
        print("[ERROR] 找不到章节「一」")
        return 1

    # 找第二节起点（第一个出现的后续章节标题）
    end = len(paragraphs)
    for i in range(start + 1, len(paragraphs)):
        if paragraphs[i] in SECTIONS and paragraphs[i] != "一":
            end = i
            break

    body = paragraphs[start + 1:end]  # 不含标题「一」本身
    title = paragraphs[0] if paragraphs else "铁锈海的女儿"

    DST.write_text(
        f"{title}\n第一节\n\n" + "\n\n".join(body) + "\n",
        encoding="utf-8"
    )
    print(f"已保存第一节到: {DST}")
    print(f"段落数: {len(body)}  字数: {sum(len(p) for p in body)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
