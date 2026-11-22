"""Headless test of Pick from Selected (colour slot and tiles) on a body with
many materials (a VRoid body: skin, hair, clothes… on one object). Object
Mode: every texture of the object is offered, not only the active slot's. Edit
Mode, the faces of one material selected: their texture, whatever the active
slot. Mixed faces: the texture with the most faces first. A texture chosen
from the list (by name) is the one set.

blender --background --python tests/run_pick_texture.py -- <model.vrm>
"""

import importlib.util
import os
import sys

import bmesh
import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = sys.argv[sys.argv.index("--") + 1:][0]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = rig
spec.loader.exec_module(rig)
rig.register()
colour = sys.modules["theater_rig.colour"]
bpy.ops.import_scene.vrm(filepath=src)
problems = []

body = max((o for o in bpy.context.view_layer.objects if o.type == "MESH"), key=lambda o: len(o.material_slots))
for o in bpy.context.view_layer.objects:
    o.select_set(o == body)
bpy.context.view_layer.objects.active = body
textured = [i for i, s in enumerate(body.material_slots) if colour.base_image(s.material) is not None]
images = {colour.base_image(body.material_slots[i].material) for i in textured}
print("materials:", len(body.material_slots), "| textured:", len(textured), "| textures:", len(images))
if len(images) < 2:
    problems.append("this model has one texture: nothing to choose between")

# Object Mode: every texture offered
found = colour.images_of_selection(bpy.context)
if {f[0] for f in found} != images:
    problems.append(f"Object Mode offers {len(found)} texture(s), not {len(images)}")

# Edit Mode: the faces of a material other than the active slot's
body.active_material_index = textured[0]
want_slot = textured[-1]
want = colour.base_image(body.material_slots[want_slot].material)
bpy.ops.object.mode_set(mode="EDIT")
bm = bmesh.from_edit_mesh(body.data)
for f in bm.faces:
    f.select = f.material_index == want_slot
bmesh.update_edit_mesh(body.data)
found = colour.images_of_selection(bpy.context)
print("edit, one material's faces:", [(f[0].name, f[2]) for f in found])
if not found or found[0][0] != want:
    problems.append(f"Edit Mode gives {found[0][0].name if found else None}, not {want.name}")
bpy.ops.theater_rig.pick_texture("INVOKE_DEFAULT")
if bpy.context.scene.theater_rig.color_image != want:
    problems.append("Pick (colour slot) didn't take the selected faces' texture")
bpy.ops.theater_rig.pick_tile_texture("INVOKE_DEFAULT")
if bpy.context.scene.theater_rig.tile_image != want:
    problems.append("Pick (tiles) didn't take the selected faces' texture")

# Mixed: 1 face of another texture's material, the rest of want's
other = next(i for i in textured if colour.base_image(body.material_slots[i].material) != want)
bm = bmesh.from_edit_mesh(body.data)
next(f for f in bm.faces if f.material_index == other).select = True
bmesh.update_edit_mesh(body.data)
found = colour.images_of_selection(bpy.context)
if len(found) < 2 or found[0][0] != want:
    problems.append(f"mixed faces: {[(f[0].name, f[2]) for f in found]}, {want.name} not first")
bpy.ops.object.mode_set(mode="OBJECT")

# Chosen from the list
pick = colour.base_image(body.material_slots[other].material)
bpy.ops.theater_rig.pick_texture("EXEC_DEFAULT", image=pick.name)
if bpy.context.scene.theater_rig.color_image != pick:
    problems.append("the texture chosen from the list isn't the one set")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
