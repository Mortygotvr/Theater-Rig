"""Headless test of Import Mixamo Animations: a VRM renamed and T-posed, a
Mixamo FBX imported onto it. The action is there (named after the file, on its
own NLA track), the FBX's objects are gone; at sampled frames each limb of the
avatar points the way Mixamo's does (the FBX loaded again to compare), the
hips at the same height relative to the legs; imported again: replaced, not
doubled; the export writes the clip.

blender --background --python tests/run_mixamo.py -- <model.vrm> <mixamo.fbx> <out.glb>
"""

import importlib.util
import json
import os
import struct
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src, fbx, out = sys.argv[sys.argv.index("--") + 1:][:3]
name = os.path.splitext(os.path.basename(fbx))[0]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = rig
spec.loader.exec_module(rig)
rig.register()
an = sys.modules["theater_rig.analyse"]
rename = sys.modules["theater_rig.rename"]
mixamo = sys.modules["theater_rig.mixamo"]
export = sys.modules["theater_rig.export"]

bpy.ops.import_scene.vrm(filepath=src)
rename.rename_to_mixamo(bpy.context)
arm = an.find_armature()
bpy.context.view_layer.objects.active = arm
bpy.ops.theater_rig.tpose()
problems = []
print("not T-posed:", mixamo.not_t_posed(arm))

objects_before = set(bpy.data.objects)
res = bpy.ops.theater_rig.import_mixamo("EXEC_DEFAULT", filepath=fbx)
if res != {"FINISHED"}:
    problems.append(f"import: {res}")
act = bpy.data.actions.get(name)
if act is None:
    problems.append(f"no action {name}")
if set(bpy.data.objects) != objects_before:
    problems.append(f"objects left from the FBX: {[o.name for o in set(bpy.data.objects) - objects_before]}")
tracks = [t for t in arm.animation_data.nla_tracks if any(s.action == act for s in t.strips)]
if len(tracks) != 1:
    problems.append(f"{len(tracks)} NLA track(s) with it")

# Again: replaced, not doubled
bpy.ops.theater_rig.import_mixamo("EXEC_DEFAULT", filepath=fbx)
act = bpy.data.actions.get(name)
if len([a for a in bpy.data.actions if a.name.startswith(name)]) != 1 or len(arm.animation_data.nla_tracks) != 1:
    problems.append(f"imported twice: {[a.name for a in bpy.data.actions]}, {len(arm.animation_data.nla_tracks)} track(s)")
print("action:", act.name, tuple(act.frame_range))

# Compare with Mixamo's own bones: the FBX loaded again
actions_before = set(bpy.data.actions)
bpy.ops.import_scene.fbx(filepath=fbx)
srcarm = next(o for o in bpy.context.selected_objects if o.type == "ARMATURE")
arm.animation_data.action = act
# Arms and legs rest the same way (T-pose): they point the same way. Every
# bone (the spine and neck rest leaning otherwise on a VRoid) turns as Mixamo's
LIMBS = ["LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm",
         "LeftUpLeg", "LeftLeg", "RightUpLeg", "RightLeg"]
ALL = LIMBS + ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "LeftFoot", "RightFoot", "LeftShoulder", "LeftHandIndex1"]
rot = lambda m: m.to_3x3().normalized().to_quaternion()
worst = (0.0, "", 0)
worst_turn = (0.0, "", 0)
f0, f1 = (int(x) for x in act.frame_range)
for f in range(f0, f1 + 1, max(1, (f1 - f0) // 12)):
    bpy.context.scene.frame_set(f)
    for b in ALL:
        pt, ps = arm.pose.bones.get(b), srcarm.pose.bones.get("mixamorig:" + b)
        if pt is None or ps is None:
            continue
        tt = rot(arm.matrix_world @ pt.matrix) @ rot(arm.matrix_world @ pt.bone.matrix_local).inverted()
        ts = rot(srcarm.matrix_world @ ps.matrix) @ rot(srcarm.matrix_world @ ps.bone.matrix_local).inverted()
        a = tt.rotation_difference(ts).angle
        a = min(a, 6.28319 - a)
        if a > worst_turn[0]:
            worst_turn = (a, b, f)
        if b in LIMBS:
            dt = (arm.matrix_world.to_3x3() @ pt.matrix.to_3x3().col[1]).normalized()
            ds = (srcarm.matrix_world.to_3x3() @ ps.matrix.to_3x3().col[1]).normalized()
            rt = (arm.matrix_world.to_3x3() @ pt.bone.matrix_local.to_3x3().col[1]).normalized()
            rs = (srcarm.matrix_world.to_3x3() @ ps.bone.matrix_local.to_3x3().col[1]).normalized()
            a = dt.angle(ds) - rt.angle(rs)   # beyond how differently they rest
            if a > worst[0]:
                worst = (a, b, f)
    # Hips: height above the feet, as a share of the leg's length
    def share(o, pre):
        p = lambda n: (o.matrix_world @ o.pose.bones[pre + n].head)
        leg = (o.matrix_world @ o.data.bones[pre + "LeftUpLeg"].head_local - o.matrix_world @ o.data.bones[pre + "LeftFoot"].head_local).length
        return (p("Hips").z - min(p("LeftFoot").z, p("RightFoot").z)) / leg
    d = abs(share(arm, "") - share(srcarm, "mixamorig:"))
    if d > 0.08:
        problems.append(f"frame {f}: hips height off by {d:.2f} leg lengths")
    # And above the floor (a hips bone that can't move keeps its height: the feet swing up instead)
    def height(o, pre):
        return (o.matrix_world @ o.pose.bones[pre + "Hips"].head).z / (o.matrix_world @ o.data.bones[pre + "Hips"].head_local).z
    d = abs(height(arm, "") - height(srcarm, "mixamorig:"))
    if d > 0.05:
        problems.append(f"frame {f}: hips at {height(arm, ''):.2f} of their rest height, Mixamo's at {height(srcarm, 'mixamorig:'):.2f}")
print("worst limb direction (beyond the rest poses' difference): %.1f deg (%s, frame %d)" % (worst[0] * 57.2958, worst[1], worst[2]))
print("worst bone turn: %.1f deg (%s, frame %d)" % (worst_turn[0] * 57.2958, worst_turn[1], worst_turn[2]))
if worst[0] * 57.2958 > 1:
    problems.append("limbs don't point as Mixamo's")
if worst_turn[0] * 57.2958 > 1:
    problems.append("bones don't turn as Mixamo's")
bpy.data.objects.remove(srcarm, do_unlink=True)
for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("Beta")]:
    bpy.data.objects.remove(o, do_unlink=True)
arm.animation_data.action = None
for a in set(bpy.data.actions) - actions_before:
    bpy.data.actions.remove(a)

# Export: the clip in the GLB
export.export_glb(bpy.context, out)
with open(out, "rb") as fh:
    data = fh.read()
n = struct.unpack("<I", data[12:16])[0]
gltf = json.loads(data[20:20 + n])
anims = [a.get("name") for a in gltf.get("animations", [])]
print("GLB animations:", anims)
if name not in anims:
    problems.append(f"{name} isn't in the GLB")
if any("mixamo.com" in (a or "") for a in anims):
    problems.append("the FBX's own action went into the GLB too")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
