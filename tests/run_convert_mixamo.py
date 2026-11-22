"""Headless test of Convert Mixamo to Animation GLB: a Mixamo FBX made into
an animation GLB next to a copy of it: one clip named after the file, the
skeleton's bones without "mixamorig:", no mesh; the scene as it was (an
avatar in it with an action of the same bone names: not in the GLB).

blender --background --python tests/run_convert_mixamo.py -- <mixamo.fbx> <out dir> [<model.vrm>]
"""

import importlib.util
import json
import os
import shutil
import struct
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = sys.argv[sys.argv.index("--") + 1:]
fbx, outdir = args[0], args[1]
vrm = args[2] if len(args) > 2 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = rig
spec.loader.exec_module(rig)
rig.register()
problems = []

if vrm:
    # An avatar with a Mixamo action of its own (same bone names)
    bpy.ops.import_scene.vrm(filepath=vrm)
    sys.modules["theater_rig.rename"].rename_to_mixamo(bpy.context)
    arm = sys.modules["theater_rig.analyse"].find_armature()
    bpy.context.view_layer.objects.active = arm
    bpy.ops.theater_rig.tpose()
    bpy.ops.theater_rig.import_mixamo("EXEC_DEFAULT", filepath=fbx)
    bpy.data.actions[os.path.splitext(os.path.basename(fbx))[0]].name = "Avatar's own"
    arm.animation_data.action = bpy.data.actions["Avatar's own"]

os.makedirs(outdir, exist_ok=True)
copy = os.path.join(outdir, "Knock Test.fbx")
shutil.copy(fbx, copy)
objects = set(bpy.data.objects)
actions = set(bpy.data.actions)
res = bpy.ops.theater_rig.convert_mixamo("EXEC_DEFAULT", filepath=copy)
out = os.path.join(outdir, "Knock Test.glb")
if res != {"FINISHED"} or not os.path.exists(out):
    problems.append(f"convert: {res}, {out} there: {os.path.exists(out)}")
if set(bpy.data.objects) != objects or set(bpy.data.actions) != actions:
    problems.append("the scene changed")
else:
    with open(out, "rb") as f:
        data = f.read()
    n = struct.unpack("<I", data[12:16])[0]
    g = json.loads(data[20:20 + n])
    anims = [a.get("name") for a in g.get("animations", [])]
    names = [nd.get("name") for nd in g["nodes"]]
    print("animations:", anims, "| nodes:", len(names), names[:4], "| meshes:", len(g.get("meshes", [])))
    if anims != ["Knock Test"]:
        problems.append(f"animations {anims}, not just Knock Test")
    if "Hips" not in names or any("mixamorig" in (x or "") for x in names):
        problems.append("bones not named Hips… without mixamorig:")
    if g.get("meshes"):
        problems.append("a mesh in it")
    print("size: %.0f KB" % (len(data) / 1024))

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
