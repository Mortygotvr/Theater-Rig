"""Headless test of Test Tile: a 2 x 2 sheet on two materials (one whose UVs
cover the whole sheet, one whose UVs sit on one cell, like VRoid's eyes).
A tile shown puts its binds on both; the arrows go through the set (and wrap);
Back to Normal puts both back exactly (the one-cell material loses the
Mapping node the test made); Export never carries a tested tile.

blender --background --python tests/run_tile_test.py -- <out.glb>
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
spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = rig
spec.loader.exec_module(rig)
rig.register()
export = sys.modules["theater_rig.export"]
tiles = sys.modules["theater_rig.tiles"]

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
    u0, v0, u1, v1 = uv_box
    for loop in obj.data.uv_layers.active.data:
        u, v = loop.uv
        loop.uv = (u0 + u * (u1 - u0), v0 + v * (v1 - v0))
    obj.parent = arm
    obj.modifiers.new("Armature", "ARMATURE").object = arm
    return mat


whole = plane("Whole", (0.0, 0.0, 1.0, 1.0), -1)
one = plane("OneCell", (0.55, 0.55, 0.95, 0.95), 1)
bpy.context.view_layer.objects.active = arm
tiles.make(arm, sheet, 2, 2, "Open, Closed, Half, Star", default_cell=1, set_name="eyes")

problems = []


def close(a, b):
    return all(abs(x - y) < 1e-5 for x, y in zip(a, b))


def mapping_nodes(mat):
    return [n for n in mat.node_tree.nodes if n.type in ("MAPPING", "UVMAP")]


whole_before = tiles.base_transform(whole)
if tiles._mapping(one) is not None:
    problems.append("the one-cell material had a Mapping node before the test")

# Show "Star" (cell 3): both materials take its binds
n = tiles.test(arm, "Star")
star = {b["material"]: b for b in tiles.stored(arm)["Star"]["binds"]}
for mat in (whole, one):
    want = star[mat.name]["scale"] + star[mat.name]["offset"]
    if not close(tiles.base_transform(mat), want):
        problems.append(f"{mat.name} shows {tiles.base_transform(mat)}, not Star's {want}")
if n != 2 or tiles.tested(arm) != "Star":
    problems.append(f"tested: {n} material(s), now {tiles.tested(arm)!r}")

# The arrows: Star -> Open (wraps), then back to Star
if tiles.step(arm, "eyes", 1) != "Open" or tiles.step(arm, "eyes", -1) != "Star":
    problems.append("the arrows don't go through the set")

# The buttons, as the panel calls them
bpy.ops.theater_rig.step_tile(set_name="eyes", by=1)
if tiles.tested(arm) != "Open":
    problems.append(f"the arrow button shows {tiles.tested(arm)!r}")
bpy.ops.theater_rig.test_tile(tile="Half")
if tiles.tested(arm) != "Half":
    problems.append(f"Test Tile shows {tiles.tested(arm)!r}")

# Back to Normal: exactly as before
bpy.ops.theater_rig.restore_tiles()
if not close(tiles.base_transform(whole), whole_before):
    problems.append(f"the whole-sheet material isn't back: {tiles.base_transform(whole)} vs {whole_before}")
if mapping_nodes(one):
    problems.append(f"the one-cell material kept the test's nodes: {[n.name for n in mapping_nodes(one)]}")
tex = next(n for n in one.node_tree.nodes if n.type == "TEX_IMAGE")
if tex.inputs["Vector"].links:
    problems.append("the one-cell texture still reads something else than its UVs")
if tiles.tested(arm) or tiles.TEST in arm:
    problems.append("the test is still marked on the armature")

# A tile left on: Export puts it back first
tiles.test(arm, "Star")
export.export_glb(bpy.context, out)
if tiles.tested(arm):
    problems.append("Export left the tile being tested")
with open(out, "rb") as f:
    data = f.read()
n = struct.unpack("<I", data[12:16])[0]
gltf = json.loads(data[20:20 + n])
for m in gltf.get("materials", []):
    info = m.get("pbrMetallicRoughness", {}).get("baseColorTexture", {})
    tt = info.get("extensions", {}).get("KHR_texture_transform")
    if m["name"] == "OneCell" and tt:
        problems.append(f"OneCell exported with the tested tile: {tt}")
    if m["name"] == "Whole" and (not tt or not close(tt.get("scale", [1, 1]) + tt.get("offset", [0, 0]), whole_before)):
        problems.append(f"Whole exported with {tt}, not its default cell {whole_before}")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
