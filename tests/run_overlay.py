"""Headless test of overlays (Rig enabled as Blender enables it): a PNG laid
over a VRM's face material. Its faces are copied a hair's width out (in a
shape key too), keep their weights (posed, the copy follows), get the
overlay's material (marked, listed); it takes a colour slot; the export has
it blended with its picture; Remove puts the mesh back as it was.

blender --background --python tests/run_overlay.py -- <model.vrm> <out dir>
"""

import json
import math
import os
import struct
import sys

import bpy
import numpy as np

vrm, outdir = sys.argv[sys.argv.index("--") + 1:][:2]
os.makedirs(outdir, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
PKG = "bl_ext.user_default.theater_rig"
ov = sys.modules[PKG + ".overlay"]
colour = sys.modules[PKG + ".colour"]
export = sys.modules[PKG + ".export"]
problems = []

bpy.ops.import_scene.vrm(filepath=vrm)
sys.modules[PKG + ".rename"].rename_to_mixamo(bpy.context)
arm = sys.modules[PKG + ".analyse"].find_armature()

# A PNG: a red square in the middle, transparent around it
png = os.path.join(outdir, "logo.png")
img = bpy.data.images.new("logo_src", 64, 64, alpha=True)
px = np.zeros((64, 64, 4), dtype=np.float32)
px[24:40, 24:40] = [1.0, 0.0, 0.0, 1.0]
img.pixels.foreach_set(px.ravel())
img.filepath_raw = png
img.file_format = "PNG"
img.save()
bpy.data.images.remove(img)

# The face material: the body's material with the most faces under the head
body = next(o for o in bpy.context.view_layer.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers))
counts = {}
for p in body.data.polygons:
    counts[p.material_index] = counts.get(p.material_index, 0) + 1
face_slot = next((i for i, s in enumerate(body.material_slots) if s.material and "face" in s.material.name.lower()), max(counts, key=counts.get))
base = body.material_slots[face_slot].material
n_base = counts.get(face_slot, 0)
n_faces, n_verts, n_slots = len(body.data.polygons), len(body.data.vertices), len(body.material_slots)
print("base:", base.name, n_base, "faces")

bpy.context.scene.theater_rig.overlay_material = base
res = bpy.ops.theater_rig.add_overlay("EXEC_DEFAULT", filepath=png)
mats = ov.overlays()
print("added:", res, [(m.name, under) for m, under in mats])
if res != {"FINISHED"} or len(mats) != 1 or mats[0][1] != base.name:
    problems.append("no overlay listed over the face")
mat = mats[0][0] if mats else None
slot = next((i for i, s in enumerate(body.material_slots) if s.material == mat), None)
copy = [p for p in body.data.polygons if p.material_index == slot]
if len(copy) != n_base:
    problems.append(f"{len(copy)} overlay faces, not {n_base}")

# Lifted along the normal, by LIFT, at rest and in a shape key; weights kept
orig = [p for p in body.data.polygons if p.material_index == face_slot]
pairs = []
for a, b in zip(orig[:50], copy[:50]):
    for va, vb in zip(a.vertices, b.vertices):
        pairs.append((va, vb))
d = [(body.data.vertices[vb].co - body.data.vertices[va].co).length for va, vb in pairs]
print("lift: %.6f .. %.6f m" % (min(d), max(d)))
if not all(abs(x - ov.LIFT) < 1e-5 for x in d):
    problems.append("the copy isn't a lift's width out")
keys = body.data.shape_keys.key_blocks if body.data.shape_keys else []
if len(keys) > 1:
    k = keys[1]
    dk = [(k.data[vb].co - k.data[va].co).length for va, vb in pairs]
    if not all(abs(x - ov.LIFT) < 1e-4 for x in dk):
        problems.append(f"shape key {k.name}: the copy isn't lifted ({min(dk):.6f}..{max(dk):.6f})")
groups = lambda v: sorted((g.group, round(g.weight, 4)) for g in body.data.vertices[v].groups)
if any(groups(va) != groups(vb) for va, vb in pairs[:200]):
    problems.append("the copy's weights differ")

# Posed: the copy follows (still a lift away)
pb = arm.pose.bones.get("Head")
pb.rotation_mode = "XYZ"
pb.rotation_euler = (math.radians(30), 0, math.radians(20))
bpy.context.view_layer.update()
ev = body.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
dp = [(ev.vertices[vb].co - ev.vertices[va].co).length for va, vb in pairs]
print("posed lift: %.6f .. %.6f m" % (min(dp), max(dp)))
if max(dp) > ov.LIFT * 3:
    problems.append("posed, the copy comes off the face")
pb.rotation_euler = (0, 0, 0)

# A colour slot on the overlay: still an overlay
colour.make_color_slot(mat.node_tree.nodes["Image Texture"].image, 5)
if not any("Color5" in m.name for m, _ in ov.overlays()):
    problems.append("the overlay lost its mark with a colour slot")

# Exported: blended, its picture
out = os.path.join(outdir, "overlay.glb")
export.export_glb(bpy.context, out)
with open(out, "rb") as fh:
    data = fh.read()
n = struct.unpack("<I", data[12:16])[0]
g = json.loads(data[20:20 + n])
em = next((m for m in g["materials"] if m["name"] == mat.name), None)
print("GLB:", em and (em["name"], em.get("alphaMode"), "texture" if em.get("pbrMetallicRoughness", {}).get("baseColorTexture") else None))
if em is None or em.get("alphaMode") != "BLEND" or not em.get("pbrMetallicRoughness", {}).get("baseColorTexture"):
    problems.append("the overlay isn't exported blended with its picture")

# Removed: the mesh as it was
name = mat.name
bpy.ops.theater_rig.remove_overlay("EXEC_DEFAULT", material=name)
print("removed:", len(body.data.polygons), len(body.data.vertices), len(body.material_slots), name in bpy.data.materials)
if (len(body.data.polygons), len(body.data.vertices), len(body.material_slots)) != (n_faces, n_verts, n_slots) or name in bpy.data.materials:
    problems.append("Remove didn't put the mesh back")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
