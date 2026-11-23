"""Headless test of Make Water: a jar (an open cylinder with a neck, walls
6 mm thick, even), turned and moved, wrongly marked by an earlier Make Water
(water_empty on it, the waves on its glass material). Select it, Make Water:
a Water object fills its inside, closed, a little inside the glass, its
floor on the jar's inner floor, a fine lid; the jar cleaned of the marks and
otherwise untouched. Exported (Export Prop): the material's extras and the
key are in the GLB.

blender --background --python tests/run_water.py -- <out.glb>
"""

import json
import math
import struct
import sys

import bmesh
import bpy

out = sys.argv[sys.argv.index("--") + 1:][0]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
PKG = "bl_ext.user_default.theater_rig"
water = sys.modules[PKG + ".water"]
export = sys.modules[PKG + ".export"]
problems = []

# The jar: radius 0.045 (0.03 at its neck), 0.12 high, open top, walls 6 mm inward
bm = bmesh.new()
rings = [(0.0, 0.045), (0.09, 0.045), (0.105, 0.03), (0.12, 0.03)]
loops = []
for z, r in rings:
    loops.append([bm.verts.new((r * math.cos(a), r * math.sin(a), z)) for a in (i / 32 * math.tau for i in range(32))])
for a, b in zip(loops, loops[1:]):
    for i in range(32):
        j = (i + 1) % 32
        bm.faces.new((a[i], a[j], b[j], b[i]))
bm.faces.new(list(reversed(loops[0])))
bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
me = bpy.data.meshes.new("Jar")
bm.to_mesh(me)
bm.free()
jar = bpy.data.objects.new("Jar", me)
bpy.context.collection.objects.link(jar)
bpy.context.view_layer.objects.active = jar
jar.select_set(True)
sol = jar.modifiers.new("S", "SOLIDIFY")
sol.thickness = 0.006
sol.offset = -1.0
sol.use_even_offset = True
bpy.ops.object.modifier_apply(modifier="S")
jar.location = (0.3, -0.1, 0.2)
jar.rotation_euler = (0, 0, math.radians(30))
glass = bpy.data.materials.new("Glass")
me.materials.append(glass)
# What the old Make Water did to it
jar.shape_key_add(name="Basis")
jar.shape_key_add(name=water.EMPTY_KEY)
glass[water.PROP] = {"height": 0.004}
bpy.context.view_layer.update()
verts_before = len(me.vertices)
matrix_before = jar.matrix_world.copy()

bpy.ops.theater_rig.make_water("EXEC_DEFAULT")
w = bpy.context.active_object
print("water:", w.name, len(w.data.vertices), "vertices")
if w == jar:
    problems.append("the jar itself was taken for the water")

# The jar: cleaned, otherwise as it was
if jar.data.shape_keys is not None or water.PROP in glass:
    problems.append("the old marks are still on the jar")
bpy.context.view_layer.update()
if len(jar.data.vertices) != verts_before or jar.matrix_world != matrix_before:
    problems.append("the jar was changed")

# The water, in the jar's space: inside its walls
to_jar = jar.matrix_world.inverted() @ w.matrix_world
pts = [to_jar @ v.co for v in w.data.vertices]
bm = bmesh.new()
bm.from_mesh(w.data)
open_edges = sum(1 for e in bm.edges if e.is_boundary)
if open_edges:
    problems.append(f"not closed: {open_edges} open edges")
bm.free()
# The inner wall: 0.039 up to the shoulder, 0.024 in the neck (between: a slope)
def inner(z):
    if z <= 0.09:
        return 0.039
    if z >= 0.105:
        return 0.024
    return 0.039 + (0.024 - 0.039) * (z - 0.09) / 0.015
outside = [p for p in pts if math.hypot(p.x, p.y) > inner(p.z) + 2e-3]
print("widest", round(max(math.hypot(p.x, p.y) for p in pts), 5), "outside the glass:", len(outside))
if outside:
    problems.append(f"{len(outside)} points outside the glass, e.g. {tuple(round(c, 4) for c in outside[0])}")
low, top = min(p.z for p in pts), max(p.z for p in pts)
print("floor", round(low, 4), "top", round(top, 4))
if not (0.006 <= low < 0.008):
    problems.append(f"its floor at {low:.4f}, not on the jar's inner floor (0.006)")
if top < 0.105:
    problems.append(f"it stops at {top:.4f}, below the neck")
lid = [p for p in pts if abs(p.z - top) < 1e-5]
print("lid points", len(lid))
if len(lid) < 200:
    problems.append(f"the lid is too coarse: {len(lid)}")
mat = w.data.materials[0]
if water.PROP not in mat or mat == glass:
    problems.append("no wave settings on the water's own material")
if water.EMPTY_KEY not in w.data.shape_keys.key_blocks:
    problems.append("no water_empty key")

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
if not any("theater_water" in e for e in extras) or not any(water.EMPTY_KEY in t for t in targets):
    problems.append("the waves or the key aren't in the GLB")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
