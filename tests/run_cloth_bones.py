"""Headless test of Make Cloth Bones: a skirt (a ring) and a cape (a sheet)
on a small body; their chains and weights made, the weights summing to one,
the top staying on the body, the hem on the last bones, no seam between
columns; made again in place; exported with `theater_cloth`; and swinging
in the spring preview.

blender --background --python tests/run_cloth_bones.py -- <out.glb>
"""

import importlib.util
import json
import math
import os
import struct
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = sys.argv[sys.argv.index("--") + 1:][0]

bpy.ops.wm.read_factory_settings(use_empty=True)
spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = rig
spec.loader.exec_module(rig)
rig.register()
cb = sys.modules["theater_rig.cloth_bones"]
sp = sys.modules["theater_rig.spring_preview"]
export = sys.modules["theater_rig.export"]

# A small body: hips, spine, chest, head
arm_data = bpy.data.armatures.new("Armature")
arm = bpy.data.objects.new("Armature", arm_data)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
for name, head, tail, parent in [("Hips", (0, 0, 0.95), (0, 0, 1.05), None), ("Spine", (0, 0, 1.05), (0, 0, 1.2), "Hips"),
                                 ("Spine2", (0, 0, 1.2), (0, 0, 1.4), "Spine"), ("Head", (0, 0, 1.5), (0, 0, 1.7), "Spine2")]:
    eb = arm_data.edit_bones.new(name)
    eb.head, eb.tail = head, tail
    if parent:
        eb.parent = arm_data.edit_bones[parent]
bpy.ops.object.mode_set(mode="OBJECT")


def mesh_object(name, bm, group):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    obj.parent = arm
    g = obj.vertex_groups.new(name=group)
    g.add([v.index for v in me.vertices], 1.0, "REPLACE")
    obj.modifiers.new("Armature", "ARMATURE").object = arm
    for v in me.vertices:
        v.select = True
    return obj


# The skirt: a flared tube, 32 around, 9 rings from the waist (0.95) to the hem (0.55)
bm = bmesh.new()
rings = []
for k in range(9):
    z = 0.95 - k * 0.05
    rad = 0.15 + k * 0.0125
    rings.append([bm.verts.new((rad * math.cos(a * math.pi / 16), rad * math.sin(a * math.pi / 16), z)) for a in range(32)])
for k in range(8):
    for a in range(32):
        bm.faces.new((rings[k][a], rings[k][(a + 1) % 32], rings[k + 1][(a + 1) % 32], rings[k + 1][a]))
skirt = mesh_object("Skirt", bm, "Hips")
bm.free()
# The cape: a sheet behind the chest (+Y is behind here), from the shoulders down
bm = bmesh.new()
grid = [[bm.verts.new((-0.2 + i * 0.05, 0.15, 1.4 - k * 0.07)) for i in range(9)] for k in range(9)]
for k in range(8):
    for i in range(8):
        bm.faces.new((grid[k][i], grid[k][i + 1], grid[k + 1][i + 1], grid[k + 1][i]))
cape = mesh_object("Cape", bm, "Spine2")
bm.free()

problems = []


def check(cond, what):
    if not cond:
        problems.append(what)


def weights(obj, v):
    return {obj.vertex_groups[g.group].name: g.weight for g in obj.data.vertices[v].groups if g.weight > 1e-6}


# The skirt: 8 columns, 4 rows
name, shape, chains = cb.make(arm, skirt, columns=8, rows=4, kind="skirt")
print(f"skirt: {name}, {shape}, chains {chains}")
check(shape == "ring", f"the skirt is a {shape}")
check(len(chains) == 8, "not 8 chains")
spring_bones = [b for b in arm.data.bones if b.name.startswith("spring_skirt_")]
check(len(spring_bones) == 8 * 5, f"{len(spring_bones)} bones (8 chains of 4 and a tip)")
check(all(arm.data.bones[c].parent.name == "Hips" for c in chains), "not hanging from the hips")
sums = [sum(weights(skirt, v.index).values()) for v in skirt.data.vertices]
check(all(abs(s - 1.0) < 1e-3 for s in sums), f"weights don't sum to 1: {min(sums):.3f}..{max(sums):.3f}")
top = max(skirt.data.vertices, key=lambda v: v.co.z).index
hem = min(skirt.data.vertices, key=lambda v: v.co.z).index
check(weights(skirt, top).get("Hips", 0) > 0.95, f"the waist isn't on the hips: {weights(skirt, top)}")
hem_w = weights(skirt, hem)
check("Hips" not in hem_w and all(k.endswith("_3") for k in hem_w), f"the hem isn't on the last bones: {hem_w}")
# Between two columns: both share it (no seam)
two = sum(1 for v in skirt.data.vertices if len({k.rsplit("_", 1)[0] for k in weights(skirt, v.index) if k.startswith("spring_")}) >= 2)
check(two > 32, f"only {two} vertices blend between columns")

# Made again (same name): the same bones and groups, no more
before = (len(arm.data.bones), len(skirt.vertex_groups))
cb.make(arm, skirt, columns=8, rows=4, kind="skirt", name=name)
check((len(arm.data.bones), len(skirt.vertex_groups)) == before, f"made again: {before} -> {(len(arm.data.bones), len(skirt.vertex_groups))}")

# The cape: a sheet, from the chest
cname, cshape, cchains = cb.make(arm, cape, columns=4, rows=3, kind="cloth")
print(f"cape: {cname}, {cshape}, parent {arm.data.bones[cchains[0]].parent.name}")
check(cshape == "sheet", f"the cape is a {cshape}")
check(arm.data.bones[cchains[0]].parent.name == "Spine2", "the cape doesn't hang from the chest")
record = cb.cloths(arm)
check(set(record) == {name, cname} and record[name]["shape"] == "ring" and len(record[cname]["chains"]) == 4, f"record: {record}")

# The preview swings them
p = sp.Preview(arm)
start = arm.matrix_world.copy()
moved = 0.0
for f in range(40):
    arm.matrix_world = Matrix.Rotation(math.radians(60.0) * min(f / 10.0, 1.0), 4, "Z") @ start
    bpy.context.view_layer.update()
    p.step(1.0 / 60.0)
    moved = max(moved, max((j.tail - j.prev_tail).length for j in p.joints))
print(f"preview: {len(p.joints)} joints, swinging up to {moved:.4f} m a frame")
check(moved > 0.002, "the cloth doesn't swing")
p.stop()
arm.matrix_world = start

# Exported: the cloths travel in the GLB
export.export_glb(bpy.context, out)
with open(out, "rb") as f:
    f.read(12)
    n = struct.unpack("<I", f.read(4))[0]
    f.read(4)
    gltf = json.loads(f.read(n))
carried = [x for x in gltf["nodes"] if "theater_cloth" in x.get("extras", {})]
check(bool(carried), "no node carries theater_cloth")
if carried:
    print("in the GLB:", sorted(json.loads(carried[0]["extras"]["theater_cloth"])))

# Taken away: its bones and groups go, the rest stays
cb.remove(arm, cname)
check(not any(b.name.startswith("spring_cloth_") for b in arm.data.bones), "the cape's bones are still there")
check(not any(g.name.startswith("spring_cloth_") for g in cape.vertex_groups), "the cape's groups are still there")
check(any(b.name.startswith("spring_skirt_") for b in arm.data.bones), "the skirt went too")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
