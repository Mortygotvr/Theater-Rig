"""Headless test of spring settings by kind: a VRM's springs renamed, then
each kind (hair, bust…) has one set of settings on the armature, the average
of its chains'; the preview reads them; Export writes each kind's on every
chain of that kind. And the colliders come only from meshes in the scene (a
copy of the body left out of it, still pointing at the armature, made them
metres wide).

blender --background --python tests/run_spring_groups.py -- <model.vrm> <out.glb>
"""

import importlib.util
import json
import os
import struct
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = sys.argv[sys.argv.index("--") + 1:]
src, out = args[0], args[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = rig
spec.loader.exec_module(rig)
rig.register()
an = sys.modules["theater_rig.analyse"]
rename = sys.modules["theater_rig.rename"]
sp = sys.modules["theater_rig.spring_preview"]
export = sys.modules["theater_rig.export"]

bpy.ops.import_scene.vrm(filepath=src)
rename.rename_to_mixamo(bpy.context)
arm = an.find_armature()
bpy.context.view_layer.objects.active = arm
problems = []

# Rename Springs (the operator): the settings by kind come with it
bpy.ops.theater_rig.rename_springs()
groups = sp.kinds(arm)
print("kinds:", {k: len(v) for k, v in groups.items()})
if not groups or not sp.grouped(arm):
    problems.append("no settings by kind after Rename Springs")
for kind, bones in groups.items():
    for k in sp.DEFAULTS:
        avg = sum(float(b[f"spring_{k}"]) for b in bones) / len(bones)
        if abs(float(arm.data[sp.kind_key(kind, k)]) - avg) > 0.002:
            problems.append(f"{kind} {k}: {arm.data[sp.kind_key(kind, k)]}, not the chains' average {avg:.3f}")

# The preview reads the kind's settings (live)
kind = "hair" if "hair" in groups else next(iter(groups))
root = groups[kind][0].name
p = sp.Preview(arm)
arm.data[sp.kind_key(kind, "gravity")] = 2.5
if abs(p.settings(root)["gravity"] - 2.5) > 1e-6:
    problems.append(f"the preview doesn't read {kind}'s settings: {p.settings(root)}")
p.stop()

# A copy of the body out of the scene, still pointing at the armature: not a collider source
body = next(o for o in bpy.context.view_layer.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers))
stray = body.copy()
stray.data = body.data.copy()
for v in stray.data.vertices:
    v.co.x = -v.co.x + 3.0   # far from the bones
before = {c[0]: c[3] for c in sp.colliders_of(arm)}
if stray in sp._avatar_meshes(arm):
    problems.append("a mesh out of the scene counts for the colliders")
after = {c[0]: c[3] for c in sp.colliders_of(arm)}
print("widest collider: %.3f m" % max(after.values()))
if before != after or max(after.values()) > 0.5:
    problems.append(f"colliders changed by a mesh out of the scene, or too wide: {max(after.values()):.2f} m")

# Export: each kind's settings on every chain of that kind, in the GLB
arm.data[sp.kind_key(kind, "stiffness")] = 0.42
export.export_glb(bpy.context, out)
with open(out, "rb") as f:
    data = f.read()
n = struct.unpack("<I", data[12:16])[0]
gltf = json.loads(data[20:20 + n])
wrong = []
count = 0
for node in gltf["nodes"]:
    name = node.get("name", "")
    if sp.kind_of(name) == kind and name.endswith("_0"):
        count += 1
        ex = node.get("extras") or {}
        if abs(ex.get("spring_stiffness", -1) - 0.42) > 1e-4 or abs(ex.get("spring_gravity", -1) - 2.5) > 1e-4:
            wrong.append((name, ex.get("spring_stiffness"), ex.get("spring_gravity")))
print(f"{kind} chains in the GLB: {count}; with the kind's settings: {count - len(wrong)}")
if count == 0 or wrong:
    problems.append(f"Export didn't write {kind}'s settings on its chains: {wrong[:3]}")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
