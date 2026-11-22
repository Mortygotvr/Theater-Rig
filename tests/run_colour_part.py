"""Headless test of colour slots on some colours of a texture (Rig enabled
as Blender enables it): a texture like a painted garment (red with a light
streak and a dark edge, a yellow stripe, grey). Chosen, its colours show as
swatches (the reds one family); only red ticked, Make Colour Slot lays the red
over the material as slot 4 (the texture under it untouched): the red follows
the slot, the yellow and grey don't. Blender shows the slot's colour (a
Multiply node); changed there, it's the colour exported (and not applied
twice). All ticked: the whole texture, as before. Remove puts it back.

blender --background --python tests/run_colour_part.py -- <out dir> [<her texture.png> <colour to tick: red|grey>]...
"""

import json
import os
import struct
import sys

import bpy
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:]
outdir = args[0]
os.makedirs(outdir, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
PKG = "bl_ext.user_default.theater_rig"
colour = sys.modules[PKG + ".colour"]
ov = sys.modules[PKG + ".overlay"]
export = sys.modules[PKG + ".export"]
problems = []
st = bpy.context.scene.theater_rig

# An armature and a plane wearing the texture
bpy.ops.object.armature_add()
arm = bpy.context.object
arm.name = "Armature"


def garment(name, pixels):
    h, w = pixels.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.pixels.foreach_set(pixels.ravel())
    img.pack()
    bpy.ops.mesh.primitive_plane_add()
    obj = bpy.context.object
    obj.name = name
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    mat.node_tree.links.new(tex.outputs["Color"], mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    obj.data.materials.append(mat)
    obj.parent = arm
    obj.modifiers.new("Armature", "ARMATURE").object = arm
    return img, mat


# Like her first texture (Blender's pixels go bottom up: it doesn't matter here)
H, W = 64, 128
px = np.zeros((H, W, 4), dtype=np.float32)
px[..., 3] = 1.0
px[:, :] = [0.21, 0.21, 0.21, 1.0]                 # dark grey
px[32:, :] = [0.79, 0.01, 0.02, 1.0]               # red
px[40:42, :] = [0.91, 0.33, 0.33, 1.0]             # its light streak
px[32:34, :] = [0.51, 0.04, 0.04, 1.0]             # its dark edge
px[32:, 56:72] = [1.0, 0.81, 0.0, 1.0]             # the yellow stripe
px[4:6, :] = [0.83, 0.83, 0.83, 1.0]               # a light line
img, mat = garment("Shirt", px)

st.color_image = img
names = [(tuple(round(c, 2) for c in it.color), round(it.share, 3)) for it in st.palette]
print("swatches:", names)
reds = [i for i, it in enumerate(st.palette) if it.color[0] > 0.4 and it.color[1] < 0.4]
if len(st.palette) != 4 or len(reds) != 1:
    problems.append(f"swatches: {names} (the reds not one family?)")
for i, it in enumerate(st.palette):
    it.change = i in reds
st.color_slot = 4
res = bpy.ops.theater_rig.make_color_slot("EXEC_DEFAULT")
parts = [m for m in bpy.data.materials if colour.PART_PROP in m]
print("made:", res, [m.name for m in parts], "| under:", mat.name, colour.base_image(mat).name)
if res != {"FINISHED"} or len(parts) != 1 or "Color4" not in parts[0].name:
    problems.append("no colour part Color4")
if mat.name != "Shirt" or colour.base_image(mat) != img or colour.preview_node(mat) is not None:
    problems.append("the texture under it was touched")
part = parts[0] if parts else None

# The red follows the slot; the yellow and the grey don't
if part is not None:
    grey_img = colour.base_image(part)
    g = colour.image_rgba(grey_img).reshape(H, W, 4)
    a_red, a_yellow, a_grey, a_line, a_streak = g[50, 10, 3], g[50, 64, 3], g[16, 10, 3], g[5, 10, 3], g[41, 10, 3]
    print("part's alpha: red %.2f streak %.2f | yellow %.2f grey %.2f line %.2f" % (a_red, a_streak, a_yellow, a_grey, a_line))
    if min(a_red, a_streak) < 0.95 or max(a_yellow, a_grey, a_line) > 0.05:
        problems.append("the part isn't the red alone")
    # Blender shows it: a Multiply node with the slot's colour
    node = colour.preview_node(part)
    if node is None:
        problems.append("Blender doesn't show the slot's colour (no Multiply node)")
    else:
        b = colour.sock(node.inputs, "B")
        print("Blender's colour:", [round(c, 3) for c in b.default_value[:3]], "| color_default:", [round(c, 3) for c in part["color_default"]])
        # Tried in Blender: blue
        b.default_value = (0.0, 0.1, 1.0, 1.0)

# Exported: the slot's colour is the node's; no factor on top (not twice)
out = os.path.join(outdir, "part.glb")
export.export_glb(bpy.context, out)
with open(out, "rb") as fh:
    data = fh.read()
n = struct.unpack("<I", data[12:16])[0]
gl = json.loads(data[20:20 + n])
em = next((m for m in gl["materials"] if part is not None and m["name"] == part.name), None)
if em is not None:
    factor = em.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
    cd = em.get("extras", {}).get("color_default")
    print("GLB:", em["name"], em.get("alphaMode"), "factor", factor, "color_default", cd and [round(c, 3) for c in cd])
    if any(abs(f - 1) > 1e-3 for f in factor[:3]):
        problems.append("the node's colour was exported as a factor too (applied twice)")
    if not cd or abs(cd[2] - 1.0) > 0.01 or cd[0] > 0.01:
        problems.append("the colour tried in Blender isn't the one exported")
    if em.get("alphaMode") != "BLEND":
        problems.append("the part isn't blended")
else:
    problems.append("the part isn't in the GLB")
if part is not None and abs(colour.sock(colour.preview_node(part).inputs, "B").default_value[2] - 1.0) > 1e-3:
    problems.append("the node's colour wasn't put back after the export")

# Removed: the part gone, the texture under it as it was
st.color_image = colour.base_image(part) if part is not None else None
res = bpy.ops.theater_rig.remove_color_slot()
left = [m for m in bpy.data.materials if colour.PART_PROP in m]
print("removed:", res, left, "| faces:", len(bpy.data.objects["Shirt"].data.polygons))
if res != {"FINISHED"} or left or len(bpy.data.objects["Shirt"].data.polygons) != 1:
    problems.append("Remove didn't take the part off")

# All ticked: the whole texture, shown in Blender
st.color_image = img
for it in st.palette:
    it.change = True
bpy.ops.theater_rig.make_color_slot("EXEC_DEFAULT")
if "Color4" not in mat.name or colour.preview_node(mat) is None:
    problems.append(f"all ticked: not the whole texture shown with its colour ({mat.name})")

# Her textures, if given: the colour ticked alone, how much is in the part
for path, want in zip(args[1::2], args[2::2]):
    her = bpy.data.images.load(path)
    her.pack()
    _, hmat = garment(os.path.splitext(os.path.basename(path))[0], colour.image_rgba(her).reshape(her.size[1], her.size[0], 4))
    st.color_image = colour.base_image(hmat)
    sw = [(it.color[:], it.share) for it in st.palette]
    pick = (lambda c: c[0] > 0.5 and c[1] < 0.3) if want == "red" else (lambda c: max(c) - min(c) < 0.05 and 0.25 < max(c) < 0.45)
    for it in st.palette:
        it.change = pick(it.color)
    print(os.path.basename(path), "swatches:", ["#%02x%02x%02x %.1f%%%s" % (*(round(v * 255) for v in c), s * 100, " ✓" if pick(c) else "") for c, s in sw])
    st.color_slot = 7 if want == "red" else 8
    bpy.ops.theater_rig.make_color_slot("EXEC_DEFAULT")
    hp = [m for m in bpy.data.materials if colour.PART_PROP in m and f"Color{st.color_slot}" in m.name]
    a = colour.image_rgba(colour.base_image(hp[0]))[:, 3] if hp else np.zeros(1)
    print("   part covers %.1f%% of the texture" % ((a > 0.5).mean() * 100))
    if not hp:
        problems.append(f"{path}: no part")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
