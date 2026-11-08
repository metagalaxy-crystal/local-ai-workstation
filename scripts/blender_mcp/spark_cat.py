"""火花猫场景构建脚本 —— 在 Blender 内部执行（由 MCP 的 execute_blender_code 送入）。

所有造型均由 bpy 程序化生成：
  - 深灰蓝毛皮的猫本体（球体/锥体/柱体拼接）
  - 橙色自发光火花沿螺旋轨迹环绕猫身
  - 合成器 Glare(Fog Glow) 让火花产生辉光
  - 输出 PNG 渲染图与 .blend 工程文件
"""

import math
import os

import bpy
from mathutils import Vector

OUTPUT_DIR = r"d:\models\output\blender_mcp"
OUTPUT_PNG = os.path.join(OUTPUT_DIR, "spark_cat.png")
OUTPUT_BLEND = os.path.join(OUTPUT_DIR, "spark_cat.blend")
RESOLUTION = 1280

os.makedirs(OUTPUT_DIR, exist_ok=True)


def clear_scene() -> None:
    """清空当前文件里的所有物体与孤立数据。"""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def make_material(name, base_color, roughness=0.6, emission=None, strength=0.0):
    """创建 Principled BSDF 材质；emission 为 None 时是普通材质。"""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = strength
    return mat


def add_sphere(name, radius, location, scale=(1.0, 1.0, 1.0), material=None,
               segments=48, rings=24, rotation=(0.0, 0.0, 0.0), shadow=True):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=segments, ring_count=rings, radius=radius, location=location,
    )
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    obj.rotation_euler = rotation
    obj.visible_shadow = shadow
    if material is not None:
        obj.data.materials.append(material)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


def add_cone(name, radius, depth, location, rotation=(0.0, 0.0, 0.0), material=None):
    bpy.ops.mesh.primitive_cone_add(
        vertices=32, radius1=radius, radius2=0.0, depth=depth,
        location=location, rotation=rotation,
    )
    obj = bpy.context.active_object
    obj.name = name
    if material is not None:
        obj.data.materials.append(material)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


def add_cylinder(name, radius, depth, location, rotation=(0.0, 0.0, 0.0), material=None):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=24, radius=radius, depth=depth, location=location, rotation=rotation,
    )
    obj = bpy.context.active_object
    obj.name = name
    if material is not None:
        obj.data.materials.append(material)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


clear_scene()

# --- 材质 -------------------------------------------------------------------
mat_fur = make_material("M_Fur", (0.028, 0.032, 0.048), roughness=0.5)
mat_belly = make_material("M_Belly", (0.10, 0.105, 0.135), roughness=0.65)
mat_eye = make_material("M_Eye", (0.35, 1.0, 0.55), roughness=0.15,
                        emission=(0.35, 1.0, 0.55), strength=6.0)
mat_pupil = make_material("M_Pupil", (0.01, 0.01, 0.015), roughness=0.1)
mat_spark = make_material("M_Spark", (1.0, 0.45, 0.08), roughness=0.3,
                          emission=(1.0, 0.36, 0.04), strength=18.0)
mat_spark_hot = make_material("M_SparkHot", (1.0, 0.85, 0.45), roughness=0.3,
                              emission=(1.0, 0.78, 0.32), strength=28.0)
mat_nose = make_material("M_Nose", (0.65, 0.22, 0.28), roughness=0.4)
mat_ground = make_material("M_Ground", (0.008, 0.008, 0.012), roughness=0.9)

# --- 猫本体 ---------------------------------------------------------------
add_sphere("CAT_Body", 1.0, (0.0, 0.0, 1.05), scale=(0.88, 1.05, 1.0), material=mat_fur)
add_sphere("CAT_Chest", 0.55, (0.0, -0.32, 1.15), scale=(1.0, 0.75, 1.05), material=mat_belly)
add_sphere("CAT_Head", 0.62, (0.0, -0.08, 2.02), scale=(1.0, 0.95, 0.92), material=mat_fur)

# 耳朵
for side in (-1, 1):
    add_cone("CAT_Ear_%s" % ("L" if side < 0 else "R"), 0.26, 0.5,
             (0.34 * side, -0.05, 2.48),
             rotation=(math.radians(-8), math.radians(14 * side), 0.0),
             material=mat_fur)

# 眼睛 + 瞳孔
for side in (-1, 1):
    add_sphere("CAT_Eye_%s" % ("L" if side < 0 else "R"), 0.13,
               (0.245 * side, -0.52, 2.12), scale=(1.0, 1.0, 1.15), material=mat_eye)
    add_sphere("CAT_Pupil_%s" % ("L" if side < 0 else "R"), 0.055,
               (0.25 * side, -0.625, 2.16), scale=(0.7, 0.5, 1.3), material=mat_pupil)

# 鼻子 + 胡须
add_sphere("CAT_Nose", 0.075, (0.0, -0.625, 1.94), scale=(1.2, 0.8, 0.9), material=mat_nose)
for side in (-1, 1):
    for idx, angle in enumerate((8, 0, -8)):
        add_cylinder("CAT_Whisker_%s%d" % ("L" if side < 0 else "R", idx), 0.008, 0.55,
                     (0.28 * side, -0.58, 1.95 + idx * 0.03),
                     rotation=(math.radians(90), 0.0, math.radians(side * (60 + angle))),
                     material=mat_belly)

# 四腿
for sx, sy in ((-0.38, -0.05), (0.38, -0.05), (-0.38, 0.12), (0.38, 0.12)):
    add_cylinder("CAT_Leg_%.2f_%.2f" % (sx, sy), 0.13, 0.72,
                 (sx * 1.05, sy, 0.34), material=mat_fur)
    add_sphere("CAT_Paw_%.2f_%.2f" % (sx, sy), 0.16, (sx * 1.05, sy - 0.03, 0.02),
               scale=(1.0, 1.15, 0.75), material=mat_belly)

# 尾巴：沿圆弧渐小的球体串
TAIL_POINTS = 14
for i in range(TAIL_POINTS):
    t = i / (TAIL_POINTS - 1)
    x = 0.55 + 0.95 * math.sin(t * math.pi * 0.85)
    z = 0.75 + 1.55 * t
    add_sphere("CAT_Tail_%02d" % i, 0.30 - 0.19 * t, (x, 0.10 + 0.16 * t, z),
               segments=24, rings=12, material=mat_fur)

# --- 火花 -----------------------------------------------------------------
# 沿螺旋线布置大小不一的发光小球，模拟猫身周围飞散的火星；
# 火花不参与投影，避免在猫身上留下黑斑。
SPARK_COUNT = 70
import random  # noqa: E402
random.seed(20261103)
for i in range(SPARK_COUNT):
    angle = i * 0.62
    radius = 1.45 + 0.55 * math.sin(i * 0.31)
    z = 0.25 + 2.55 * (i / SPARK_COUNT)
    x = radius * math.cos(angle)
    y = radius * math.sin(angle) - 0.1
    size = 0.016 + 0.03 * (0.5 + 0.5 * math.sin(i * 1.7))
    mat = mat_spark_hot if i % 5 == 0 else mat_spark
    add_sphere("SPARK_%03d" % i, size, (x, y, z), segments=10, rings=6,
               material=mat, shadow=False)

# 尾巴尖端的火花簇，强化「火花猫」的尾迹感
TAIL_TIP = Vector((1.45, 0.30, 2.05))
for i in range(26):
    offset = Vector((random.uniform(-0.42, 0.42),
                     random.uniform(-0.32, 0.32),
                     random.uniform(-0.10, 0.55)))
    size = 0.010 + 0.028 * random.random()
    add_sphere("SPARK_TAIL_%02d" % i, size, TAIL_TIP + offset, segments=8, rings=6,
               material=mat_spark_hot if i % 3 == 0 else mat_spark, shadow=False)

# 地面
bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, -0.02))
ground = bpy.context.active_object
ground.name = "GROUND"
ground.data.materials.append(mat_ground)

# --- 灯光 -----------------------------------------------------------------
bpy.ops.object.light_add(type="AREA", location=(3.2, -4.5, 4.6))
key = bpy.context.active_object
key.name = "LGT_Key"
key.data.energy = 300
key.data.size = 5.0
key.data.color = (1.0, 0.86, 0.72)
key.rotation_euler = (math.radians(48), 0.0, math.radians(38))

bpy.ops.object.light_add(type="AREA", location=(-3.6, 3.2, 3.4))
rim = bpy.context.active_object
rim.name = "LGT_Rim"
rim.data.energy = 340
rim.data.size = 4.0
rim.data.color = (1.0, 0.42, 0.12)
rim.rotation_euler = (math.radians(62), 0.0, math.radians(-135))

# --- 相机 -----------------------------------------------------------------
CAM_LOC = Vector((4.0, -5.8, 2.95))
CAM_TARGET = Vector((0.0, 0.0, 1.42))
bpy.ops.object.camera_add(location=CAM_LOC)
cam = bpy.context.active_object
cam.name = "CAM_Main"
cam.data.lens = 58
direction = CAM_TARGET - CAM_LOC
cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

# --- 世界与环境 -----------------------------------------------------------
world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.012, 0.014, 0.022, 1.0)
bg.inputs["Strength"].default_value = 1.0

# --- 渲染设置 -------------------------------------------------------------
scene = bpy.context.scene
try:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
except TypeError:
    scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = RESOLUTION
scene.render.resolution_y = RESOLUTION
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = OUTPUT_PNG
try:
    scene.eevee.taa_render_samples = 64
except AttributeError:
    scene.eevee.taa_samples = 64

# 合成器辉光（Blender 5.x 用 node group + 菜单输入，旧版回退 node_tree）
COMPOSITOR_OK = False
try:
    scene.use_nodes = True
    if hasattr(scene, "compositing_node_group"):
        tree = bpy.data.node_groups.new("Compositing", "CompositorNodeTree")
        scene.compositing_node_group = tree
        tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        rl = tree.nodes.new("CompositorNodeRLayers")
        out = tree.nodes.new("NodeGroupOutput")
        tree.links.new(rl.outputs["Image"], out.inputs["Image"])
    else:
        tree = scene.node_tree
        for node in list(tree.nodes):
            tree.nodes.remove(node)
        rl = tree.nodes.new("CompositorNodeRLayers")
        out = tree.nodes.new("CompositorNodeComposite")
        tree.links.new(rl.outputs["Image"], out.inputs["Image"])

    # 5.x 的 Glare 是资产节点，参数变成输入插槽；失败则保留直通链路。
    glare = tree.nodes.new("CompositorNodeGlare")
    if "Type" in glare.inputs:
        glare.inputs["Type"].default_value = "Fog Glow"
        glare.inputs["Quality"].default_value = "High"
        glare.inputs["Threshold"].default_value = 1.0
        glare.inputs["Size"].default_value = 8.0
        glare.inputs["Strength"].default_value = 1.0
    else:
        glare.glare_type = "FOG_GLOW"
        glare.quality = "HIGH"
        glare.threshold = 1.0
        glare.size = 7
    tree.links.new(rl.outputs["Image"], glare.inputs["Image"])
    tree.links.new(glare.outputs["Image"], out.inputs["Image"])
    COMPOSITOR_OK = True
except Exception as ex:  # 合成器不可用时不影响直通出图
    COMPOSITOR_OK = False
    print("compositor skipped: %s" % ex)

# --- 渲染与保存 -----------------------------------------------------------
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=OUTPUT_BLEND)

result = {
    "status": "ok",
    "render": OUTPUT_PNG,
    "blend": OUTPUT_BLEND,
    "objects": len(bpy.data.objects),
    "sparks": SPARK_COUNT,
    "resolution": RESOLUTION,
    "engine": scene.render.engine,
    "compositor": COMPOSITOR_OK,
}
