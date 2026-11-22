"""Headless test of tile testing and saving (Rig enabled as Blender enables
it, so its save handlers run): Back to Normal puts a material's texture
placement back exactly, its rotation and mode too; saving the .blend while a
tile is tested saves it as normal, and the tile shows again after.

blender --background --python tests/run_tile_save.py -- <out dir>
"""

import os
import sys

import bpy

outdir = sys.argv[sys.argv.index("--") + 1:][0]
os.makedirs(outdir, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
tiles = sys.modules["bl_ext.user_default.theater_rig.tiles"]
problems = []

bpy.ops.object.armature_add()
arm = bpy.context.object
arm.name = "Armature"
sheet = bpy.data.images.new("Face.png", 64, 64)
sheet.pixels = [0.5] * (64 * 64 * 4)
sheet.pack()
bpy.ops.mesh.primitive_plane_add()
obj = bpy.context.object
mat = bpy.data.materials.new("Face")
mat.use_nodes = True
nodes = mat.node_tree.nodes
tex = nodes.new("ShaderNodeTexImage")
tex.image = sheet
mat.node_tree.links.new(tex.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
obj.data.materials.append(mat)
bpy.context.view_layer.objects.active = arm
tiles.make(arm, sheet, 2, 2, "Normal, Shy, Gloom, Salty", set_name="Emotion")

# The texture's placement given a rotation and another mode, as a material can have
node = tiles._mapping(mat)
node.vector_type = "TEXTURE"
node.inputs["Rotation"].default_value = (0.0, 0.0, 0.3)
node.inputs["Location"].default_value = (0.1, 0.2, 0.0)
before = tiles._snapshot(mat)

def same(a, b):
    return a["type"] == b["type"] and all(abs(x - y) < 1e-6 for k in ("location", "rotation", "scale") for x, y in zip(a[k], b[k]))

tiles.test(arm, "Salty")
tiles.restore(arm)
if not same(tiles._snapshot(mat), before):
    problems.append(f"Back to Normal: {tiles._snapshot(mat)}, not {before}")

# Saved while "Salty" is tested
tiles.test(arm, "Salty")
salty = tiles._snapshot(mat)
path = os.path.join(outdir, "tile_save.blend")
bpy.ops.wm.save_as_mainfile(filepath=path)
print("after saving: tested", tiles.tested(arm))
if tiles.tested(arm) != "Salty" or not same(tiles._snapshot(mat), salty):
    problems.append("the tile isn't shown again after saving")
bpy.ops.wm.open_mainfile(filepath=path)
arm = bpy.data.objects["Armature"]
mat = bpy.data.materials["Face"]
print("reopened: tested", repr(tiles.tested(arm)), "| placement", tiles._snapshot(mat))
if tiles.tested(arm) or not same(tiles._snapshot(mat), before):
    problems.append("the file was saved with the tile tested")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
