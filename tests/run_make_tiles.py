"""Headless test of Make Tiles: a 2 x 2 sheet used by two meshes, one whose
UVs cover the whole sheet and one whose UVs sit on one cell (like VRoid's
eyes). Tiles made, exported; the GLB carries them as `theater_tiles`, and the
whole-sheet material shows its default cell (KHR_texture_transform).

blender --background --python tests/run_make_tiles.py -- <out.glb>
"""

import importlib.util
import json
import os
import struct
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = sys.argv[sys.argv.index("--") + 1:][0]

bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
except Exception:
    pass

spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = rig
spec.loader.exec_module(rig)
rig.register()
export = sys.modules["theater_rig.export"]
tiles = sys.modules["theater_rig.tiles"]

# An armature, and two planes it deforms, both on the sheet
bpy.ops.object.armature_add()
arm = bpy.context.object
arm.name = "Armature"
sheet = bpy.data.images.new("Eyes.png", 64, 64)
sheet.pixels = [0.5] * (64 * 64 * 4)
sheet.pack()


def plane(name, uv_box, x):
    bpy.ops.mesh.primitive_plane_add(location=(x, 0, 1))
    obj = bpy.context.object
    obj.name = name
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = sheet
    mat.node_tree.links.new(tex.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
    obj.data.materials.append(mat)
    # UVs: the plane's corners onto uv_box (Blender's v up)
    u0, v0, u1, v1 = uv_box
    for loop in obj.data.uv_layers.active.data:
        u, v = loop.uv
        loop.uv = (u0 + u * (u1 - u0), v0 + v * (v1 - v0))
    obj.parent = arm
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    return mat


whole = plane("Whole", (0.0, 0.0, 1.0, 1.0), -1)
# The top right cell (glTF: column 1, row 0); Blender's v up: 0.5–1
one = plane("OneCell", (0.55, 0.55, 0.95, 0.95), 1)

problems = []
bpy.context.view_layer.objects.active = arm
count, kinds = tiles.make(arm, sheet, 2, 2, "Open, Closed, , Star", default_cell=1, set_name="eyes")
print("made:", count, kinds)
if kinds != {"Whole": "sheet", "OneCell": "cell"}:
    problems.append(f"kinds: {kinds}")
made = tiles.stored(arm)
if tiles.sets(arm) != {"eyes": ["Open", "Closed", "Eyes_2", "Star"]}:
    problems.append(f"sets: {tiles.sets(arm)}")


def bind(name, mat):
    return next(b for b in made[name]["binds"] if b["material"] == mat)


def near(a, b):
    return all(abs(x - y) < 1e-5 for x, y in zip(a, b))


# Whole sheet: Star (cell 3) is the bottom right quarter
b = bind("Star", "Whole")
if not (near(b["scale"], [0.5, 0.5]) and near(b["offset"], [0.5, 0.5])):
    problems.append(f"Whole Star: {b}")
# One cell (its own: column 1, row 0): Open (cell 0) moves it left by half
b = bind("Open", "OneCell")
if not (near(b["scale"], [1, 1]) and near(b["offset"], [-0.5, 0.0])):
    problems.append(f"OneCell Open: {b}")
b = bind("Star", "OneCell")
if not near(b["offset"], [0.0, 0.5]):
    problems.append(f"OneCell Star: {b}")
if tiles.base_transform(whole) != [0.5, 0.5, 0.5, 0.0] and not near(tiles.base_transform(whole), [0.5, 0.5, 0.5, 0.0]):
    problems.append(f"Whole default: {tiles.base_transform(whole)}")

# Made again with other names: the set's old ones go; another set stays
tiles.make(arm, sheet, 2, 2, "A, B, C, D", default_cell=1, set_name="eyes")
tiles.make(arm, sheet, 1, 2, "Up, Down")
if tiles.sets(arm) != {"eyes": ["A", "B", "C", "D"], "Eyes": ["Up", "Down"]}:
    problems.append(f"remade: {tiles.sets(arm)}")
if tiles.remove_set(arm, "Eyes") != 2:
    problems.append("remove_set")
# (Up / Down moved the whole sheet's default cell: the 2 x 2 again)
tiles.make(arm, sheet, 2, 2, "A, B, C, D", default_cell=1, set_name="eyes")
# The old form (binds alone) reads as the set "expressions"
old = tiles.normalised({"Wink": [{"material": "Whole", "scale": [1, 1], "offset": [0, 0]}]})
if old != {"Wink": {"set": "expressions", "order": 0, "binds": [{"material": "Whole", "scale": [1, 1], "offset": [0, 0]}]}}:
    problems.append(f"old form: {old}")
# Export keeps them (store merges, doesn't wipe)
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
    print("in the GLB:", data["A"])
    if sorted(data) != ["A", "B", "C", "D"] or data["D"]["set"] != "eyes" or data["D"]["order"] != 3:
        problems.append(f"GLB tiles: {sorted(data)}")
mats = {m["name"]: m for m in gltf["materials"]}
tt = mats["Whole"]["pbrMetallicRoughness"]["baseColorTexture"].get("extensions", {}).get("KHR_texture_transform")
print("Whole's texture transform:", tt)
if not tt or not (near(tt.get("scale", [1, 1]), [0.5, 0.5]) and near(tt.get("offset", [0, 0]), [0.5, 0.0])):
    problems.append(f"Whole's default cell in the GLB: {tt}")
if mats["OneCell"]["pbrMetallicRoughness"]["baseColorTexture"].get("extensions", {}).get("KHR_texture_transform"):
    problems.append("OneCell got a texture transform")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
