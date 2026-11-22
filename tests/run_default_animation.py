"""Headless test of the avatar's Default animation: Export GLB writes it
alone (not the avatar's other actions), first, named after it, tagged
theater_default; the avatar's action and NLA as they were. Without one: no
animation in the GLB.

blender --background --python tests/run_default_animation.py -- <model.vrm> <out dir>
"""

import json
import math
import os
import struct
import sys

import bpy

vrm, outdir = sys.argv[sys.argv.index("--") + 1:][:2]
os.makedirs(outdir, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
PKG = "bl_ext.user_default.theater_rig"
export = sys.modules[PKG + ".export"]
problems = []


def anims(path):
    with open(path, "rb") as f:
        data = f.read()
    n = struct.unpack("<I", data[12:16])[0]
    return [(a.get("name"), (a.get("extras") or {}).get("theater_default")) for a in json.loads(data[20:20 + n]).get("animations", [])]


bpy.ops.import_scene.vrm(filepath=vrm)
sys.modules[PKG + ".rename"].rename_to_mixamo(bpy.context)
arm = sys.modules[PKG + ".analyse"].find_armature()
bpy.context.view_layer.objects.active = arm
bpy.ops.theater_rig.tpose()


def action(name, bone, deg):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    pb = arm.pose.bones[bone]
    pb.rotation_mode = "XYZ"
    for f, a in ((1, 0), (24, deg), (48, 0)):
        pb.rotation_euler = (math.radians(a), 0, 0)
        pb.keyframe_insert("rotation_euler", frame=f)
    pb.rotation_euler = (0, 0, 0)
    return act


breathe = action("Breathe", "Spine1", 4)
wave = action("Wave", "RightArm", 60)   # active after this
ad = arm.animation_data
track = ad.nla_tracks.new()
track.strips.new("Breathe", 1, breathe)

# No default: no animation
out = os.path.join(outdir, "no_default.glb")
export.export_glb(bpy.context, out)
print("without default:", anims(out))
if anims(out):
    problems.append(f"animations without a default: {anims(out)}")

# Default: Breathe alone, tagged
setattr(arm.data, export.DEFAULT_PROP, "Breathe")
out = os.path.join(outdir, "default.glb")
export.export_glb(bpy.context, out)
print("with default:", anims(out))
if anims(out) != [("Breathe", True)]:
    problems.append(f"animations: {anims(out)}, not Breathe alone, tagged")
if ad.action != wave or not ad.use_nla or len(ad.nla_tracks) != 1:
    problems.append("the avatar's action or NLA changed")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
