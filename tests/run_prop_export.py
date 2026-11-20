"""Headless test of Export Prop GLB: a mesh parented to an armature (moved,
turned, its bone posed) exported alone: no armature, no skin, its shape key
kept, and every vertex exactly where it is in Blender at rest (in glTF's Y up),
so Theater Puppet draws it lined up with the avatar.

blender --background --python tests/run_prop_export.py -- <out.glb>
"""

import importlib.util
import json
import math
import os
import struct
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = sys.argv[sys.argv.index("--") + 1:][0]

bpy.ops.wm.read_factory_settings(use_empty=True)
spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = rig
spec.loader.exec_module(rig)
rig.register()
export = sys.modules["theater_rig.export"]

# An armature moved and turned, its bone posed
arm = bpy.data.objects.new("Armature", bpy.data.armatures.new("Armature"))
bpy.context.collection.objects.link(arm)
arm.location = (0.3, -0.2, 0.1)
arm.rotation_euler = (0, 0, math.radians(30))
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
eb = arm.data.edit_bones.new("Hips")
eb.head, eb.tail = (0, 0, 1.0), (0, 0, 1.2)
bpy.ops.object.mode_set(mode="OBJECT")
arm.pose.bones["Hips"].rotation_mode = "XYZ"
arm.pose.bones["Hips"].rotation_euler = (math.radians(40), 0, 0)

# The prop: a box by the hip, parented to the armature, bent by it, with a shape key
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=0.1)
me = bpy.data.meshes.new("Holster")
bm.to_mesh(me)
bm.free()
prop = bpy.data.objects.new("Holster", me)
bpy.context.collection.objects.link(prop)
prop.location = (0.18, 0.02, 0.95)
prop.parent = arm
prop.matrix_parent_inverse = arm.matrix_world.inverted()
g = prop.vertex_groups.new(name="Hips")
g.add([v.index for v in me.vertices], 1.0, "REPLACE")
prop.modifiers.new("Armature", "ARMATURE").object = arm
prop.shape_key_add(name="Basis")
key = prop.shape_key_add(name="Fcl_MTH_A")
key.data[0].co.z += 0.02
prop["color_default"] = [1.0, 0.5, 0.2]
bpy.context.view_layer.update()

# Where its vertices are at rest, in the world, in glTF's axes (x, z, -y)
rest = [prop.matrix_world @ v.co for v in me.vertices]
want = np.array([(p.x, p.z, -p.y) for p in rest])

for o in bpy.context.view_layer.objects:
    o.select_set(o == prop)
bpy.context.view_layer.objects.active = arm
problems = []
done = export.export_prop(bpy.context, out)
if [o.name for o in done] != ["Holster"]:
    problems.append(f"exported {done}")

# The selection and the armature modifier are as they were
if not prop.modifiers["Armature"].show_viewport or not prop.select_get() or arm.select_get():
    problems.append("the modifier or the selection wasn't put back")

with open(out, "rb") as f:
    data = f.read()
n = struct.unpack("<I", data[12:16])[0]
gltf = json.loads(data[20:20 + n])
binary = data[20 + n + 8:]
if gltf.get("skins"):
    problems.append("it has a skin")
names = [x.get("name") for x in gltf["nodes"]]
if "Armature" in names or "Hips" in names:
    problems.append(f"the armature came along: {names}")


def node_matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"]).reshape(4, 4).T
    t = node.get("translation", [0, 0, 0])
    r = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    q = Quaternion((r[3], r[0], r[1], r[2]))
    m = Matrix.Translation(t) @ q.to_matrix().to_4x4() @ Matrix.Diagonal((s[0], s[1], s[2], 1.0))
    return np.array(m)


parents = {c: i for i, nd in enumerate(gltf["nodes"]) for c in nd.get("children", [])}


def world(i):
    m = node_matrix(gltf["nodes"][i])
    return world(parents[i]) @ m if i in parents else m


mesh_node = next(i for i, nd in enumerate(gltf["nodes"]) if "mesh" in nd)
mesh = gltf["meshes"][gltf["nodes"][mesh_node]["mesh"]]
acc = gltf["accessors"][mesh["primitives"][0]["attributes"]["POSITION"]]
view = gltf["bufferViews"][acc["bufferView"]]
start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
pos = np.frombuffer(binary[start:start + acc["count"] * 12], dtype="<f4").reshape(-1, 3)
M = world(mesh_node)
got = (M[:3, :3] @ pos.T).T + M[:3, 3]
# Each of Blender's vertices has one at the same place in the GLB (the exporter may split them)
worst = max(np.min(np.linalg.norm(got - w, axis=1)) for w in want)
print(f"{len(got)} vertices in the GLB; farthest from Blender's: {worst * 1000:.3f} mm")
if worst > 1e-4:
    problems.append(f"not lined up: {worst * 1000:.2f} mm off")
targets = mesh.get("extras", {}).get("targetNames", [])
print("shape keys:", targets, "| extras:", gltf["nodes"][mesh_node].get("extras"))
if "Fcl_MTH_A" not in targets:
    problems.append("the shape key is gone")
if "color_default" not in (gltf["nodes"][mesh_node].get("extras") or {}):
    problems.append("its custom properties are gone")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
