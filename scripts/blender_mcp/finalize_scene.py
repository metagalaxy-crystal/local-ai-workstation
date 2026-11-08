"""收尾脚本：统一渲染设置、自动取景、灯光兜底、保存工程。

由 agent_demo.py 读取后经 MCP 的 execute_blender_code 送入 Blender 执行。
占位符 __BLEND_PATH__ / __PNG_PATH__ 在发送前替换为实际路径。
"""

import bpy
from mathutils import Vector

BLEND_PATH = r"__BLEND_PATH__"
PNG_PATH = r"__PNG_PATH__"

s = bpy.context.scene

# --- 渲染设置 ---
try:
    s.render.engine = "BLENDER_EEVEE_NEXT"
except TypeError:
    s.render.engine = "BLENDER_EEVEE"
s.render.resolution_x = 1280
s.render.resolution_y = 1280
s.render.resolution_percentage = 100
s.render.image_settings.file_format = "PNG"
s.render.film_transparent = False
s.render.filepath = PNG_PATH
try:
    s.eevee.taa_render_samples = 64
except AttributeError:
    pass
try:
    s.view_settings.look = "AgX - Medium High Contrast"
except Exception:
    pass
# 发光火花容易把高光冲到纯白，压一点曝光保住橙金色
s.view_settings.exposure = -0.6

# --- 世界兜底：没有世界节点时补一个暗色背景 ---
if s.world is None:
    s.world = bpy.data.worlds.new("World")
if not s.world.use_nodes:
    s.world.use_nodes = True
bg = s.world.node_tree.nodes.get("Background")
if bg is not None:
    color = tuple(bg.inputs["Color"].default_value)[:3]
    if max(color) > 0.15:  # 模型给了浅色背景时压暗，保持主体对比
        bg.inputs["Color"].default_value = (0.02, 0.022, 0.03, 1.0)

# 小型自发光物体（火花）不投影，避免在地面留下黑斑
for o in s.objects:
    if o.type != "MESH" or not o.data.materials or max(o.dimensions) > 0.3:
        continue
    mat = o.data.materials[0]
    if not mat.use_nodes:
        continue
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf and bsdf.inputs["Emission Strength"].default_value > 0:
        o.visible_shadow = False

# --- 自动取景：按所有网格物体的包围盒重新放相机 ---
mesh_objs = [o for o in s.objects if o.type == "MESH" and o.visible_get()]
pts = []
for o in mesh_objs:
    for corner in o.bound_box:
        pts.append(o.matrix_world @ Vector(corner))

# 过滤地面/背景大平面（面积过大且很薄），避免包围盒被拉爆
def _is_ground(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [p.x for p in corners]
    ys = [p.y for p in corners]
    zs = [p.z for p in corners]
    return (max(xs) - min(xs)) * (max(ys) - min(ys)) > 50.0 and (max(zs) - min(zs)) < 0.1

subject_pts = []
for o in mesh_objs:
    if _is_ground(o):
        continue
    for corner in o.bound_box:
        subject_pts.append(o.matrix_world @ Vector(corner))
if not subject_pts:
    subject_pts = pts

center = sum(subject_pts, Vector()) / len(subject_pts)
extent = max(
    max(p.x for p in subject_pts) - min(p.x for p in subject_pts),
    max(p.y for p in subject_pts) - min(p.y for p in subject_pts),
    max(p.z for p in subject_pts) - min(p.z for p in subject_pts),
) or 2.0

cam = s.camera
if cam is None:
    cam_data = bpy.data.cameras.new("MCP_Camera")
    cam = bpy.data.objects.new("MCP_Camera", cam_data)
    s.collection.objects.link(cam)
    s.camera = cam

direction = Vector((0.85, -1.0, 0.48)).normalized()
distance = max(6.0, extent * 3.0)
cam.location = center + direction * distance
cam.data.lens = 55
cam.data.clip_start = 0.05
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()

# --- 灯光兜底：场景里没有任何灯时补三点光 ---
if not [o for o in s.objects if o.type == "LIGHT"]:
    specs = [
        ("LGT_Key", (center.x + 3.0, center.y - 4.0, center.z + 4.5), 400, (1.0, 0.88, 0.74)),
        ("LGT_Rim", (center.x - 3.5, center.y + 3.0, center.z + 3.0), 300, (1.0, 0.45, 0.15)),
        ("LGT_Fill", (center.x + 1.0, center.y + 4.0, center.z + 2.0), 120, (0.55, 0.8, 1.0)),
    ]
    for name, loc, energy, color in specs:
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.size = 4.0
        data.color = color
        light = bpy.data.objects.new(name, data)
        s.collection.objects.link(light)
        light.location = loc
        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()

bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)

result = {
    "saved": BLEND_PATH,
    "camera": s.camera.name,
    "subject_center": [round(v, 2) for v in center],
    "subject_extent": round(extent, 2),
    "lights": len([o for o in s.objects if o.type == "LIGHT"]),
    "meshes": len(mesh_objs),
}
