"""Headless test of every button in order, on a VRM:
Detoonify, Rename Bones, Rename Springs, Align Bones, T-Pose (no-op, then on an
A-posed copy), Remove VRM Data, then a GLB export.

blender --background --python tests/run_pipeline.py -- <model.vrm> <out.glb>
"""

import importlib.util
import json
import math
import os
import struct
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = sys.argv[sys.argv.index("--") + 1:]
src, out = args[0], args[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
bpy.ops.import_scene.vrm(filepath=src)

spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = rig
spec.loader.exec_module(rig)
rig.register()
an = sys.modules["theater_rig.analyse"]
tp = sys.modules["theater_rig.tpose"]

problems = []
arm = an.find_armature()
ops = bpy.ops.theater_rig


def mesh_points(name):
    obj = bpy.data.objects[name]
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return [v.co.copy() for v in ev.data.vertices]


def worst_move(a, b):
    return max((p - q).length for p, q in zip(a, b))


def weighted(obj, group):
    vg = obj.vertex_groups.get(group)
    return 0 if vg is None else sum(1 for v in obj.data.vertices for g in v.groups if g.group == vg.index)


print("detoonify:", ops.detoonify())
print("rename_mixamo:", ops.rename_mixamo())

hair = bpy.data.objects["Hair"]
deformed = [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]
spring_weights = sum(weighted(o, b.name) for o in deformed for b in arm.data.bones if b.name.startswith("J_Sec_"))
print("rename_springs:", ops.rename_springs())
names = [b.name for b in arm.data.bones]
spring_names = [n for n in names if n.startswith("spring_")]
print(f"  spring bones: {len(spring_names)}, sample {spring_names[:4]}")
if any(n.startswith("J_Sec_") for n in names):
    problems.append(f"spring bones left unrenamed: {[n for n in names if n.startswith('J_Sec_')][:5]}")
root = arm.data.bones.get("spring_hair_1_0")
if root is None or "spring_stiffness" not in root.keys():
    problems.append("spring_hair_1_0 has no spring_stiffness")
else:
    print(f"  spring_hair_1_0 settings: { {k: round(root[k], 3) for k in root.keys() if k.startswith('spring_')} }")
new_weights = sum(weighted(o, n) for o in deformed for n in spring_names)
print(f"  weighted vertices on spring bones: {spring_weights} before, {new_weights} after")
if new_weights != spring_weights:
    problems.append(f"spring weights changed: {spring_weights} -> {new_weights}")

before = {n: mesh_points(n) for n in ("Face", "Body", "Hair")}
print("align_bones:", ops.align_bones())
for n, pts in before.items():
    d = worst_move(pts, mesh_points(n))
    print(f"  {n}: mesh moved at most {d * 1000:.4f} mm")
    if d > 1e-5:
        problems.append(f"Align moved {n} by {d * 1000:.3f} mm")
hand = arm.data.bones["LeftHand"]
mid = arm.data.bones["LeftHandMiddle1"]
if (hand.tail_local - mid.head_local).length > 1e-4:
    problems.append("LeftHand doesn't point at LeftHandMiddle1")

print("tpose (already T):", ops.tpose())
if tp.needed(arm):
    problems.append(f"still off a T-pose: {tp.needed(arm)}")

# A-pose the model (arms 40 degrees down), make that the rest, then T-pose it back
face = bpy.data.objects["Face"]
blink = face.data.shape_keys.key_blocks.get("eyeBlinkLeft")
keys_before = len(face.data.shape_keys.key_blocks)
for side, sign in (("Left", 1), ("Right", -1)):
    pb = arm.pose.bones[f"{side}Arm"]
    head = pb.matrix.translation.copy()
    rot = Matrix.Rotation(math.radians(-40 * sign), 4, "Y")
    pb.matrix = Matrix.Translation(head) @ rot @ Matrix.Translation(-head) @ pb.matrix
bpy.context.view_layer.update()
for o in tp._deformed_meshes(arm):
    tp._bake_mesh(o)
tp._apply_pose_as_rest(arm)
bpy.context.view_layer.update()
off = tp.needed(arm)
print(f"  A-posed: {[(n, round(math.degrees(a))) for n, a in off]}")
hand_pts_a = mesh_points("Body")
print("tpose (from A):", ops.tpose())
left = tp.needed(arm)
if left:
    problems.append(f"T-pose left bones off: {[(n, round(math.degrees(a), 1)) for n, a in left]}")
if len(face.data.shape_keys.key_blocks) != keys_before:
    problems.append("shape keys lost in T-pose")
blink = face.data.shape_keys.key_blocks["eyeBlinkLeft"]
basis = face.data.shape_keys.key_blocks[0]
blink_move = max((a.co - b.co).length for a, b in zip(blink.data, basis.data))
print(f"  eyeBlinkLeft still moves the eyelid by up to {blink_move * 1000:.2f} mm")
if blink_move < 1e-4:
    problems.append("eyeBlinkLeft no longer changes anything")
# Arms came back up: the left hand's highest skin vertex should be near shoulder height again
arm_z = (arm.matrix_world @ arm.data.bones["LeftHand"].head_local).z
shoulder_z = (arm.matrix_world @ arm.data.bones["LeftArm"].head_local).z
print(f"  left hand height vs shoulder: {(arm_z - shoulder_z) * 100:.1f} cm")
if abs(arm_z - shoulder_z) > 0.02:
    problems.append("left hand not at shoulder height after T-pose")

print("remove_vrm:", ops.remove_vrm())
# The VRM add-on, while enabled, re-creates empty defaults: check they hold nothing
ext = arm.data.vrm_addon_extension
humanoid_left = [b.node.bone_name for b in ext.vrm0.humanoid.human_bones if b.node.bone_name]
springs_left = len(ext.vrm0.secondary_animation.bone_groups) + len(ext.spring_bone1.springs)
mtoon_left = [m.name for m in bpy.data.materials if m.vrm_addon_extension.mtoon1.enabled]
print(f"  VRM data left: humanoid {len(humanoid_left)}, spring groups {springs_left}, MToon {len(mtoon_left)}")
if humanoid_left or springs_left or mtoon_left:
    problems.append("VRM data not emptied")
rep = an.analyse()
print(f"  after removal: roles {len(rep.roles)} (from {rep.roles[0].source if rep.roles else '-'}), springs {len(rep.springs)}, VRM '{rep.vrm_spec}'")
if len(rep.roles) < 54 or len(rep.springs) != 17:
    problems.append(f"Analyse after removal: {len(rep.roles)} roles, {len(rep.springs)} springs")

bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_extras=True)
data = open(out, "rb").read()
gltf = json.loads(data[20:20 + struct.unpack_from("<I", data, 12)[0]])
node = next((n for n in gltf["nodes"] if n.get("name") == "spring_hair_1_0"), None)
print("  GLB spring_hair_1_0 extras:", node.get("extras") if node else None)
if not node or "spring_stiffness" not in node.get("extras", {}):
    problems.append("spring settings not in the GLB")

for p in problems:
    print("!!", p)
print(f"RESULT: {len(problems)} problem(s)")
