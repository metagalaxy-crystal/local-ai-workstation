from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
import os

# 创建工作目录
output_dir = os.path.join(os.getcwd(), '永劫无间角色设定')
os.makedirs(output_dir, exist_ok=True)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

# 颜色方案
DARK_BG = RGBColor(0x0D, 0x0D, 0x1A)  # 深空背景
ACCENT_GOLD = RGBColor(0xFF, 0xD7, 0x00)  # 金色
ACCENT_RED = RGBColor(0xC4, 0x1E, 0x3A)  # 红色
ACCENT_BLUE = RGBColor(0x1E, 0x3A, 0xC4)  # 蓝色
ACCENT_GREEN = RGBColor(0x1E, 0xC4, 0x3A)  # 绿色
ACCENT_PURPLE = RGBColor(0x6A, 0x0D, 0xA0)  # 紫色
ACCENT_ORANGE = RGBColor(0xFF, 0x6B, 0x00)  # 橙色
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY = RGBColor(0xCC, 0xCC, 0xCC)
DARK_TEXT = RGBColor(0x1A, 0x1A, 0x2E)

def add_background(slide, color):
    """添加背景色"""
    background = slide.background
    fill = background.fill
    fill.solid()
    fill.fore_color.rgb = color

def add_shape(slide, left, top, width, height, color, alpha=None):
    """添加形状"""
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape

def add_text_box(slide, left, top, width, height, text, font_size=18, color=WHITE, bold=False, alignment=PP_ALIGN.LEFT, font_name='微软雅黑'):
    """添加文本框"""
    text_box = slide.shapes.add_textbox(left, top, width, height)
    tf = text_frame = text_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color
    p.font.bold = bold
    p.alignment = alignment
    p.font.name = font_name
    return text_box

def add_bullet_text(text_frame, text, font_size=14, color=LIGHT_GRAY, bullet=False, level=0):
    """添加项目符号文本"""
    p = text_frame.add_paragraph()
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color
    p.font.name = '微软雅黑'
    p.level = level
    p.space_after = Pt(4)
    return p

def create_slide_header(slide, title, subtitle=None):
    """创建统一的标题栏"""
    # 顶部装饰线
    add_shape(slide, Inches(0), Inches(0), prs.slide_width, Inches(0.08), ACCENT_GOLD)
    # 标题
    add_text_box(slide, Inches(0.8), Inches(0.3), Inches(10), Inches(0.8), title, 36, ACCENT_GOLD, True, PP_ALIGN.LEFT)
    # 底部装饰线
    add_shape(slide, Inches(0.8), Inches(1.15), Inches(4), Inches(0.04), ACCENT_RED)
    if subtitle:
        add_text_box(slide, Inches(0.8), Inches(1.25), Inches(10), Inches(0.5), subtitle, 16, LIGHT_GRAY, False, PP_ALIGN.LEFT)

# ==================== 第1页：封面 ====================
slide1 = prs.slides.add_slide(prs.slide_layouts[6])  # 空白布局
add_background(slide1, DARK_BG)

# 装饰元素
add_shape(slide1, Inches(0), Inches(0), prs.slide_width, Inches(0.05), ACCENT_GOLD)
add_shape(slide1, Inches(0), Inches(7.45), prs.slide_width, Inches(0.05), ACCENT_GOLD)

# 左侧大标题
add_text_box(slide1, Inches(1.5), Inches(1.0), Inches(10), Inches(1.5), 
             "永劫无间", 72, ACCENT_GOLD, True, PP_ALIGN.LEFT)

# 副标题
add_text_box(slide1, Inches(1.5), Inches(2.5), Inches(10), Inches(0.8), 
             "角色剧情设定集", 42, WHITE, False, PP_ALIGN.LEFT)

# 装饰线
add_shape(slide1, Inches(1.5), Inches(3.4), Inches(5), Inches(0.05), ACCENT_RED)

# 简介
add_text_box(slide1, Inches(1.5), Inches(3.7), Inches(10), Inches(2), 
             "由网易开发的多人动作竞技游戏\n融合东方玄幻与武侠元素\n在神秘结界中展开生死对决", 20, LIGHT_GRAY, False, PP_ALIGN.LEFT)

# 底部信息
add_text_box(slide1, Inches(1.5), Inches(6.0), Inches(10), Inches(0.5), 
             "角色设定 · 背景故事 · 武器系统", 16, ACCENT_GOLD, False, PP_ALIGN.LEFT)

# 右侧装饰图案（用文本模拟）
add_shape(slide1, Inches(10), Inches(1.0), Inches(0.05), Inches(5), ACCENT_GOLD)
add_shape(slide1, Inches(10.05), Inches(1.0), Inches(0.02), Inches(5), ACCENT_RED)

# ==================== 第2页：世界观设定 ====================
slide2 = prs.slides.add_slide(prs.slide_layouts[6])
add_background(slide2, DARK_BG)
create_slide_header(slide2, "世界观设定", "永劫之地的起源与命运")

# 左侧：世界观描述
add_shape(slide2, Inches(0.8), Inches(1.6), Inches(5.5), Inches(5.5), RGBColor(0x1A, 0x1A, 0x30))
add_text_box(slide2, Inches(1.0), Inches(1.8), Inches(5.0), Inches(0.5), 
             "永劫之地", 28, ACCENT_GOLD, True, PP_ALIGN.LEFT)

tf = add_text_box(slide2, Inches(1.0), Inches(2.5), Inches(5.0), Inches(4.0), "", 14, LIGHT_GRAY, False, PP_ALIGN.LEFT).text_frame
tf.paragraphs[0].text = "永劫之地是一个被神秘力量封印的异世界，"
tf.paragraphs[0].font.size = Pt(14)
tf.paragraphs[0].font.color.rgb = LIGHT_GRAY
tf.paragraphs[0].font.name = '微软雅黑'

tf2 = add_text_box(slide2, Inches(1.0), Inches(3.2), Inches(5.0), Inches(3.5), "", 14, WHITE, False, PP_ALIGN.LEFT).text_frame
tf2.paragraphs[0].text = "远古时期，天地间出现了一道名为"永劫"的神秘裂缝，将无数生灵吸入其中。这里充满了古老的灵力与神秘的宝物，同时也潜伏着无尽的危险。"
tf2.paragraphs[0].font.size = Pt(14)
tf2.paragraphs[0].font.color.rgb = WHITE
tf2.paragraphs[0].font.name = '微软雅黑'

add_text_box(slide2, Inches(1.0), Inches(4.8), Inches(5.0), Inches(2.0), 
             "在这片土地上，来自不同世界的英雄们为了生存与荣耀，在永劫之地的各个角落展开激烈的战斗。他们争夺着能够改变命运的神器，也在战斗中逐渐揭开永劫之地背后的真相。", 14, LIGHT_GRAY, False, PP_ALIGN.LEFT)

# 右侧：核心设定
add_shape(slide2, Inches(7.0), Inches(1.6), Inches(5.5), Inches(5.5), RGBColor(0x1A, 0x1A, 0x30))
add_text_box(slide2, Inches(7.2), Inches(1.8), Inches(5.0), Inches(0.5), 
             "核心设定", 28, ACCENT_GOLD, True, PP_ALIGN.LEFT)

items = [
    ("🔥 聚窟洲", "永劫之地的主要战场，充满神秘力量的岛屿"),
    ("⚔️ 振刀系统", "独特的格挡反击机制，考验玩家操作"),
    ("🏹 飞索系统", "自由移动与战斗的核心机制"),
    ("💎 魂玉系统", "装备搭配与技能强化的关键"),
    ("🌀 永劫裂缝", "连接不同世界的神秘通道"),
    ("🗡️ 神兵利器", "传说中的神器，拥有强大的力量")
]

for i, (title, desc) in enumerate(items):
    y = 2.6 + i * 0.75
    add_shape(slide2, Inches(7.2), Inches(y), Inches(0.3), Inches(0.3), ACCENT_RED)
    add_text_box(slide2, Inches(7.7), Inches(y - 0.05), Inches(4.5), Inches(0.3), title, 16, WHITE, True, PP_ALIGN.LEFT)
    add_text_box(slide2, Inches(7.7), Inches(y + 0.25), Inches(4.5), Inches(0.3), desc, 12, LIGHT_GRAY, False, PP_ALIGN.LEFT)

print("Slide 1-2 created successfully")
prs.save(os.path.join(output_dir, '永劫无间角色设定_部分.pptx'))
print("Saved to:", os.path.join(output_dir, '永劫无间角色设定_部分.pptx'))
