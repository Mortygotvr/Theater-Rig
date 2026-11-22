"""Headless test of Make Colour Slot on a mid-grey texture (a fabric at about
36%, like a painted grey top): the grey copy is brightened (its lightest part
white), so a colour picked shows at its own brightness; its starting colour
is darkened as much, so grey x starting colour is still what it showed.

blender --background --python tests/run_colour_bright.py
"""

import sys

import bpy
import numpy as np

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
colour = sys.modules["bl_ext.user_default.theater_rig.colour"]
problems = []

# A grey fabric (0.30-0.38, a weave), transparent around it
w = h = 64
rng = np.random.default_rng(1)
px = np.zeros((h, w, 4), dtype=np.float32)
fab = 0.30 + 0.08 * rng.random((48, 48))
px[8:56, 8:56, :3] = fab[..., None]
px[8:56, 8:56, 3] = 1.0
img = bpy.data.images.new("Fabric", w, h, alpha=True)
img.pixels.foreach_set(px.ravel())
mat = bpy.data.materials.new("Top")
mat.use_nodes = True
tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
tex.image = img
mat.node_tree.links.new(tex.outputs["Color"], mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])

grey, mats = colour.make_color_slot(img, 4)
g = np.empty(w * h * 4, dtype=np.float32)
grey.pixels.foreach_get(g)
g = g.reshape(h, w, 4)
seen = g[..., 3] > 0.5
top = float(np.percentile(g[..., 0][seen], 95))
tint = np.array(mats[0]["color_default"])
print("grey copy: top %.3f, starting colour %s" % (top, np.round(tint, 3)))
if abs(top - 1.0) > 0.02:
    problems.append(f"the grey copy's lightest isn't white ({top:.3f})")
back = (g[..., :3] * tint)[seen].mean(axis=0)
orig = px[..., :3][px[..., 3] > 0.5].mean(axis=0)
print("as it was: %s, now (grey x starting colour) %s" % (np.round(orig, 3), np.round(back, 3)))
if np.abs(back - orig).max() > 0.01:
    problems.append("grey x starting colour isn't what it showed")

# Removed: the material back on its own texture, its name and colour as they were
mat = mats[0]
bpy.context.scene.theater_rig.color_image = grey
res = bpy.ops.theater_rig.remove_color_slot()
print("removed:", res, mat.name, colour.base_image(mat).name, "color_default" in mat)
if res != {"FINISHED"} or colour.base_image(mat) != img or mat.name != "Top" or "color_default" in mat:
    problems.append("Remove Colour Slot didn't put it back")
# A copy made before it remembered: found by its name ("Fabric_Color6" from "Fabric")
grey, mats = colour.make_color_slot(img, 6)
del grey[colour.FROM_PROP]
original, _ = colour.remove_color_slot(grey)
if original != img:
    problems.append("an older copy didn't find its texture by name")
print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
