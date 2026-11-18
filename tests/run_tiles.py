"""Headless test of the tile textures: a VRM whose expressions move a texture
(VRM 0.x _MainTex_ST), exported; the GLB's armature node carries them as
`theater_tiles`, in glTF's texture coordinates.

blender --background --python tests/run_tiles.py -- <model.vrm> <out.glb>
"""

import importlib.util
import json
import os
import struct
import sys

import bpy

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
export = sys.modules["theater_rig.export"]
tiles = sys.modules["theater_rig.tiles"]

problems = []
arm = an.find_armature()
found = tiles.collect(arm)
print(f"tiles in the VRM: {len(found)} expression(s): {sorted(found)}")
if not found:
    problems.append("no tiles found")

result = export.export_glb(bpy.context, out)
print("export:", result[1:])

with open(out, "rb") as f:
    f.read(12)
    length = struct.unpack("<I", f.read(4))[0]
    f.read(4)
    gltf = json.loads(f.read(length))
carried = [n for n in gltf["nodes"] if "theater_tiles" in n.get("extras", {})]
if not carried:
    problems.append("no node carries theater_tiles")
else:
    data = json.loads(carried[0]["extras"]["theater_tiles"])
    print(f"in the GLB, on node {carried[0].get('name')!r}: {len(data)} expression(s)")
    for name in sorted(data)[:3]:
        print(f"  {name}: {data[name]}")
    if set(data) != set(found):
        problems.append("the GLB's tiles differ from the VRM's")
    names = {m["name"] for m in gltf["materials"]}
    missing = {b["material"] for binds in data.values() for b in binds} - names
    if missing:
        problems.append(f"tile materials not in the GLB: {missing}")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
