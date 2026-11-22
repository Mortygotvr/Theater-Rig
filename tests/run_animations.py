"""Headless test of the animation buttons (Rig enabled as Blender enables it,
so the exporter calls its contact hook):

- Import Mixamo: the FBX as its own skeleton named after the file (bones
  without "mixamorig:", its action named after it), the avatar untouched;
  imported again: replaced, not doubled.
- Export Animation, the imported skeleton and the avatar's (a "Wave" made on
  it) selected: <name>.glb each, one clip named after the action, no mesh,
  each with its contact frame; the VRM add-on's T-Pose not exported.
- Convert: a GLB next to the FBX; the scene as it was.

blender --background --python tests/run_animations.py -- <model.vrm> <mixamo.fbx> <out dir>
"""

import json
import math
import os
import shutil
import struct
import sys

import bpy

vrm, fbx, outdir = sys.argv[sys.argv.index("--") + 1:][:3]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
PKG = "bl_ext.user_default.theater_rig"
an = sys.modules[PKG + ".analyse"]
ax = sys.modules[PKG + ".anim_export"]
problems = []
scene = bpy.context.scene
fps = scene.render.fps / scene.render.fps_base


def glb(path):
    with open(path, "rb") as fh:
        data = fh.read()
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n])


# The avatar, as Rig makes it
bpy.ops.import_scene.vrm(filepath=vrm)
sys.modules[PKG + ".rename"].rename_to_mixamo(bpy.context)
avatar = an.find_armature()
bpy.context.view_layer.objects.active = avatar
bpy.ops.theater_rig.tpose()
avatar_bones = sorted(b.name for b in avatar.data.bones)

shutil.rmtree(outdir, ignore_errors=True)
os.makedirs(outdir)
src = os.path.join(outdir, "Knock Test.fbx")
shutil.copy(fbx, src)

# Import Mixamo, twice
for _ in range(2):
    res = bpy.ops.theater_rig.import_mixamo("EXEC_DEFAULT", filepath=src)
    if res != {"FINISHED"}:
        problems.append(f"import: {res}")
skels = [o for o in bpy.data.objects if o.type == "ARMATURE" and o != avatar]
acts = [a.name for a in bpy.data.actions if a.name.startswith("Knock Test")]
print("skeletons:", [o.name for o in skels], "| actions:", acts)
if [o.name for o in skels] != ["Knock Test"] or acts != ["Knock Test"]:
    problems.append("import twice: not one skeleton and one action named Knock Test")
skel = bpy.data.objects.get("Knock Test")
if skel is None or not ax.is_mixamo(skel) or any("mixamorig" in b.name for b in skel.data.bones):
    problems.append("the imported skeleton's bones aren't Hips, Spine… without mixamorig:")
if sorted(b.name for b in avatar.data.bones) != avatar_bones or (avatar.animation_data and (avatar.animation_data.action or len(avatar.animation_data.nla_tracks))):
    problems.append("the avatar was changed by the import")

# (The FBX import set the scene to Mixamo's 30 fps)
fps = scene.render.fps / scene.render.fps_base
print("scene fps after import:", fps)

# Edited in Blender: a contact on the imported animation
mk = skel.animation_data.action.pose_markers.new("contact")
mk.frame = 40

# Wave, made on the avatar's skeleton, a contact at frame 10
ad = avatar.animation_data or avatar.animation_data_create()
wave = bpy.data.actions.new("Wave")
ad.action = wave
pb = avatar.pose.bones["RightArm"]
pb.rotation_mode = "XYZ"
for f, a in ((1, 0), (10, 60), (20, 0)):
    pb.rotation_euler = (0, 0, math.radians(a))
    pb.keyframe_insert("rotation_euler", frame=f)
pb.rotation_euler = (0, 0, 0)
wave.pose_markers.new("contact").frame = 10

# Export Animation: both selected
anims = os.path.join(outdir, "anims")
for o in bpy.context.view_layer.objects:
    o.select_set(o in (skel, avatar))
bpy.context.view_layer.objects.active = skel
res = bpy.ops.theater_rig.export_animations("EXEC_DEFAULT", directory=anims)
files = sorted(os.listdir(anims)) if os.path.isdir(anims) else []
print("exported:", res, files)
if files != ["Knock Test.glb", "Wave.glb"]:
    problems.append(f"exported {files}, not Knock Test.glb and Wave.glb")
want_contact = {"Knock Test": 39 / fps, "Wave": 9 / fps}
for f in files:
    g = glb(os.path.join(anims, f))
    clips = [(a.get("name"), (a.get("extras") or {}).get("theater_contacts")) for a in g.get("animations", [])]
    print(" ", f, clips, "meshes:", len(g.get("meshes", [])))
    name = f[:-4]
    if [c[0] for c in clips] != [name]:
        problems.append(f"{f}: clips {clips}")
    elif not clips[0][1] or abs(clips[0][1][0] - want_contact[name]) > 1e-3:
        problems.append(f"{f}: contact {clips[0][1]}, not {want_contact[name]:.3f} s")
    if g.get("meshes"):
        problems.append(f"{f}: a mesh in it")
if ad.action != wave or not ad.use_nla:
    problems.append("the avatar's action or NLA changed by the export")

# Convert: next to the FBX, the scene as it was
objects, actions = set(bpy.data.objects), set(bpy.data.actions)
scene.render.fps = 24
timing = (scene.render.fps, scene.frame_start, scene.frame_end)
conv = os.path.join(outdir, "Convert Test.fbx")
shutil.copy(fbx, conv)
res = bpy.ops.theater_rig.convert_mixamo("EXEC_DEFAULT", filepath=conv)
out = os.path.join(outdir, "Convert Test.glb")
if res != {"FINISHED"} or not os.path.exists(out):
    problems.append(f"convert: {res}")
elif [a.get("name") for a in glb(out).get("animations", [])] != ["Convert Test"]:
    problems.append(f"convert: clips {[a.get('name') for a in glb(out).get('animations', [])]}")
if set(bpy.data.objects) != objects or set(bpy.data.actions) != actions:
    problems.append("Convert changed the scene")
if (scene.render.fps, scene.frame_start, scene.frame_end) != timing:
    problems.append(f"Convert changed the frame rate or range: {(scene.render.fps, scene.frame_start, scene.frame_end)}, was {timing}")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
