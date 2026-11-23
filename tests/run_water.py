"""Headless test of Make Water: a jar (an open cylinder, walls 6 mm thick),
its inner wall and inner bottom selected in Edit Mode. The water: a closed
mesh, its skin facing out, a little inside the glass, a lid fine enough for
waves, the shape key water_empty, a material with theater_water. Exported
(Export Prop): the material's extras and the key are in the GLB.

blender --background --python tests/run_water.py -- <out.glb>
"""

import json
import math
import struct
import sys

import bmesh
import bpy
from mathutils import Vector

out = sys.argv[sys.argv.index("--") + 1:][0]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
PKG = "bl_ext.user_default.theater_rig"
water = sys.modules[PKG + ".water"]
export = sys.modules[PKG + ".export"]
problems = []

# The jar: radius 0.045, 0.12 high, open top, solidified (applied) 6 mm inward
bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.045, radius2=0.045, depth=0.12)
bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z > 0.9], context="FACES")
me = bpy.data.meshes.new("Jar")
bm.to_mesh(me)
bm.free()
jar = bpy.data.objects.new("Jar", me)
bpy.context.collection.objects.link(jar)
jar.location = (0.3, 0.0, 0.06)
bpy.context.view_layer.objects.active = jar
jar.select_set(True)
sol = jar.modifiers.new("S", "SOLIDIFY")
sol.thickness = 0.006
sol.offset = -1.0
sol.use_even_offset = True
bpy.ops.object.modifier_apply(modifier="S")

# Its inner faces: the wall facing the axis, the bottom inside facing up
for p in me.polygons:
    c, n = p.center, p.normal
    radial = Vector((c.x, c.y, 0)).normalized()
    inner_wall = n.dot(radial) < -0.5
    inner_bottom = n.z > 0.9 and c.z < 0.0
    p.select = inner_wall or inner_bottom
print("selected", sum(p.select for p in me.polygons), "of", len(me.polygons))
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.theater_rig.make_water("EXEC_DEFAULT")
w = bpy.context.active_object
print("water:", w.name, len(w.data.vertices), "vertices", bpy.context.mode)

bm = bmesh.new()
bm.from_mesh(w.data)
open_edges = sum(1 for e in bm.edges if e.is_boundary)
if open_edges:
    problems.append(f"not closed: {open_edges} open edges")
# Its skin faces out: the wall faces point away from the axis
out_ok = all(f.normal.dot(Vector((f.calc_center_median().x, f.calc_center_median().y, 0)).normalized()) > 0.3
             for f in bm.faces if abs(f.normal.z) < 0.3)
if not out_ok:
    problems.append("its walls don't face out")
# A little inside the glass (inner radius 0.039)
rmax = max(math.hypot(v.co.x, v.co.y) for v in bm.verts)
far = max(bm.verts, key=lambda v: math.hypot(v.co.x, v.co.y))
print("widest", round(rmax, 5), "at z", round(far.co.z, 4), "normal", tuple(round(c, 2) for c in far.normal), "faces", len(far.link_faces))
if not (0.0375 < rmax < 0.039):
    problems.append(f"not just inside the glass: widest {rmax:.5f}")
top = max(v.co.z for v in bm.verts)
lid = [v for v in bm.verts if v.co.z > top - 0.002 and math.hypot(v.co.x, v.co.y) < 0.03]
print("lid inside vertices", len(lid))
if len(lid) < 30:
    problems.append(f"the lid is too coarse for waves: {len(lid)} inside vertices")
bm.free()
keys = w.data.shape_keys.key_blocks if w.data.shape_keys else []
if water.EMPTY_KEY not in keys or keys[water.EMPTY_KEY].value != 0.0:
    problems.append("no water_empty key at 0")
mat = w.data.materials[0]
print("material", mat.name, dict(mat[water.PROP]))
if abs(mat[water.PROP]["height"] - 0.004) > 1e-6:
    problems.append("wave settings not on the material")
if w.rotation_euler[:] != (0.0, 0.0, 0.0) or tuple(w.scale) != (1.0, 1.0, 1.0):
    problems.append("rotation / scale not applied")

# Exported as a prop: the extras and the key in the GLB
for o in bpy.context.view_layer.objects:
    o.select_set(o == w)
export.export_prop(bpy.context, out)
with open(out, "rb") as f:
    data = f.read()
n = struct.unpack("<I", data[12:16])[0]
g = json.loads(data[20:20 + n])
extras = [m.get("extras", {}) for m in g["materials"]]
targets = [m.get("extras", {}).get("targetNames", []) for m in g["meshes"]]
print("GLB material extras", extras, "targets", targets)
if not any("theater_water" in e for e in extras):
    problems.append("theater_water not in the GLB")
if not any(water.EMPTY_KEY in t for t in targets):
    problems.append("water_empty not in the GLB")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
