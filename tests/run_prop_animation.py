"""Headless test of Export Prop with shape key (blendshape) animations: each
action on the selected meshes' shape keys (the active one, those on their NLA
tracks) is in the GLB, named after it; an action on nothing selected isn't;
the meshes' actions as they were.

blender --background --python tests/run_prop_animation.py -- <out dir>
"""

import json
import os
import struct
import sys

import bpy

outdir = sys.argv[sys.argv.index("--") + 1:][0]
os.makedirs(outdir, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
export = sys.modules["bl_ext.user_default.theater_rig.export"]
problems = []


def anims(path):
    with open(path, "rb") as f:
        data = f.read()
    n = struct.unpack("<I", data[12:16])[0]
    g = json.loads(data[20:20 + n])
    return sorted((a.get("name"), tuple(sorted({c["target"]["path"] for c in a["channels"]}))) for a in g.get("animations", []))


def keyed_mesh(name):
    bpy.ops.mesh.primitive_cube_add()
    o = bpy.context.active_object
    o.name = name
    o.shape_key_add(name="Basis")
    k = o.shape_key_add(name="Grow")
    for v in k.data:
        v.co *= 1.5
    return o, k


def shape_action(o, k, name, peak):
    for f, v in ((1, 0.0), (12, peak), (24, 0.0)):
        k.value = v
        k.keyframe_insert("value", frame=f)
    act = o.data.shape_keys.animation_data.action
    act.name = name
    act.use_fake_user = True
    return act


prop, grow = keyed_mesh("Tentacle")
pulse = shape_action(prop, grow, "Pulse", 1.0)
# A second one, stashed on an NLA track; then a new active one
ad = prop.data.shape_keys.animation_data
track = ad.nla_tracks.new()
track.strips.new("Pulse", 1, pulse)
ad.action = None
wiggle = shape_action(prop, grow, "Wiggle", 0.5)
# Another mesh's, not selected: stays out
other, ok = keyed_mesh("Other")
shape_action(other, ok, "Elsewhere", 1.0)

for o in bpy.context.view_layer.objects:
    o.select_set(o == prop)
out = os.path.join(outdir, "prop.glb")
export.export_prop(bpy.context, out)
got = anims(out)
print("prop animations:", got)
if [n for n, _ in got] != ["Pulse", "Wiggle"] or any(p != ("weights",) for _, p in got):
    problems.append(f"animations: {got}, not Pulse and Wiggle (weights)")
if ad.action != wiggle or len(ad.nla_tracks) != 1:
    problems.append("the mesh's action or NLA changed")

# Nothing animated: no animation
bpy.ops.mesh.primitive_cube_add()
plain = bpy.context.active_object
for o in bpy.context.view_layer.objects:
    o.select_set(o == plain)
out = os.path.join(outdir, "plain.glb")
export.export_prop(bpy.context, out)
print("plain:", anims(out))
if anims(out):
    problems.append(f"plain prop has animations: {anims(out)}")

# Bound to an armature (an avatar's, animated): it goes with it, skinned; the
# armature's action stays out, the shape keys' are in
bpy.ops.object.armature_add()
arm = bpy.context.active_object
arm.name = "Avatar"
arm.data.bones[0].name = "Spine"
arm.animation_data_create()
wave = bpy.data.actions.new("AvatarWave")
wave.use_fake_user = True
arm.animation_data.action = wave
pb = arm.pose.bones["Spine"]
for f, a in ((1, 0.0), (12, 0.5)):
    pb.rotation_quaternion = (1, a, 0, 0)
    pb.keyframe_insert("rotation_quaternion", frame=f)
pb.rotation_quaternion = (1, 0, 0, 0)
prop.vertex_groups.new(name="Spine").add(range(len(prop.data.vertices)), 1.0, "REPLACE")
mod = prop.modifiers.new("Armature", "ARMATURE")
mod.object = arm
for o in bpy.context.view_layer.objects:
    o.select_set(o == prop)
out = os.path.join(outdir, "bound.glb")
export.export_prop(bpy.context, out)
with open(out, "rb") as f:
    data = f.read()
n = struct.unpack("<I", data[12:16])[0]
g = json.loads(data[20:20 + n])
nodes = [x.get("name") for x in g["nodes"]]
print("bound:", anims(out), "skins", len(g.get("skins", [])), nodes)
if len(g.get("skins", [])) != 1 or "Spine" not in nodes or "Other" in nodes:
    problems.append(f"bound prop: skins {len(g.get('skins', []))}, nodes {nodes}")
if [a for a, _ in anims(out)] != ["Pulse", "Wiggle"]:
    problems.append(f"bound prop animations: {anims(out)}")
if not mod.show_viewport or arm.animation_data.action != wave:
    problems.append("the armature modifier or the armature's action changed")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
