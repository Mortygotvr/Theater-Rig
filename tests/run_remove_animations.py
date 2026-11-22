"""Headless test of Remove Animations: an avatar with an active action, one
on an NLA track, one kept by a fake user, a shape-key animation on its body,
the VRM add-on's T-Pose, and a Default animation; plus an imported Mixamo
skeleton (its action moves bones of the same names). Remove Animations
deletes the avatar's all but its Default; the Mixamo one stays; Export GLB
then has the Default alone. Unticked: the Default goes too, and the GLB has
no animation.

blender --background --python tests/run_remove_animations.py -- <model.vrm> <mixamo.fbx> <out dir>
"""

import json
import math
import os
import struct
import sys

import bpy

vrm, fbx, outdir = sys.argv[sys.argv.index("--") + 1:][:3]
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
    return [a.get("name") for a in json.loads(data[20:20 + n]).get("animations", [])]


bpy.ops.import_scene.vrm(filepath=vrm)
sys.modules[PKG + ".rename"].rename_to_mixamo(bpy.context)
arm = sys.modules[PKG + ".analyse"].find_armature()
bpy.context.view_layer.objects.active = arm
bpy.ops.theater_rig.tpose()


def action(name, bone):
    act = bpy.data.actions.new(name)
    ad = arm.animation_data or arm.animation_data_create()
    keep = ad.action
    ad.action = act
    pb = arm.pose.bones[bone]
    pb.rotation_mode = "XYZ"
    for f, a in ((1, 0), (20, 30)):
        pb.rotation_euler = (math.radians(a), 0, 0)
        pb.keyframe_insert("rotation_euler", frame=f)
    pb.rotation_euler = (0, 0, 0)
    ad.action = keep
    return act


breathe = action("Breathe", "Spine1")
breathe.use_fake_user = True
on_track = action("Old Track", "LeftArm")
arm.animation_data.nla_tracks.new().strips.new("Old Track", 1, on_track)
kept = action("Kept Only", "RightArm")
kept.use_fake_user = True
arm.animation_data.action = action("Active One", "Head")
# A shape-key animation on the body
body = next(o for o in bpy.context.view_layer.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers))
if not body.data.shape_keys or len(body.data.shape_keys.key_blocks) < 2:
    if not body.data.shape_keys:
        body.shape_key_add(name="Basis")
    body.shape_key_add(name="Test Key")
key = body.data.shape_keys.key_blocks[1]
key.value = 0.0
key.keyframe_insert("value", frame=1)
key.value = 1.0
key.keyframe_insert("value", frame=10)
face = body.data.shape_keys.animation_data.action
setattr(arm.data, export.DEFAULT_PROP, "Breathe")

# An imported Mixamo skeleton: its own action, untouched
bpy.ops.theater_rig.import_mixamo("EXEC_DEFAULT", filepath=fbx)
mixamo_action = bpy.data.objects[os.path.splitext(os.path.basename(fbx))[0]].animation_data.action
mixamo_name = mixamo_action.name
bpy.context.view_layer.objects.active = arm

found = [a.name for a in sys.modules[PKG + ".strip"].avatar_animations(arm, breathe)]
print("to remove:", found)
want = sorted(["Active One", "Old Track", "Kept Only", face.name] + (["T-Pose"] if "T-Pose" in bpy.data.actions else []))
if found != want:
    problems.append(f"found {found}, not {want}")

bpy.ops.theater_rig.remove_animations("EXEC_DEFAULT")
left = sorted(a.name for a in bpy.data.actions)
print("actions left:", left)
if sorted([mixamo_name, "Breathe"]) != left:
    problems.append(f"left {left}, not the Mixamo one and Breathe")
if arm.animation_data.action is not None or len(arm.animation_data.nla_tracks) or (body.data.shape_keys.animation_data and body.data.shape_keys.animation_data.action):
    problems.append("the avatar still has an action or a track")
out = os.path.join(outdir, "kept.glb")
export.export_glb(bpy.context, out)
print("GLB:", anims(out))
if anims(out) != ["Breathe"]:
    problems.append(f"GLB animations {anims(out)}, not Breathe alone")

# The Default too
bpy.ops.theater_rig.remove_animations("EXEC_DEFAULT", keep_default=False)
out = os.path.join(outdir, "none.glb")
export.export_glb(bpy.context, out)
print("then:", sorted(a.name for a in bpy.data.actions), "| GLB:", anims(out))
if "Breathe" in bpy.data.actions or anims(out) or getattr(arm.data, export.DEFAULT_PROP):
    problems.append("the Default stayed")
if mixamo_name not in bpy.data.actions:
    problems.append("the Mixamo skeleton's action went")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
