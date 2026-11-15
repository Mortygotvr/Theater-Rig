"""Headless test: rename bones to Mixamo and check nothing lost track of them.

blender --background --python tests/run_rename.py -- <model.vrm> <out.glb>
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
bpy.ops.import_scene.vrm(filepath=src)

spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
theater_rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = theater_rig
spec.loader.exec_module(theater_rig)
theater_rig.register()
an = sys.modules["theater_rig.analyse"]
cv = sys.modules["theater_rig.conventions"]

arm = an.find_armature()
before_roles = {r.role: r.bone for r in an.analyse().roles}
before_springs = [(s.target, list(s.roots)) for s in an.analyse().springs]
meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]
weights_before = {o.name: {vg.name: sum(1 for v in o.data.vertices for g in v.groups if g.group == vg.index) for vg in o.vertex_groups} for o in meshes}

print("operator:", bpy.ops.theater_rig.rename_mixamo())

problems = []
after = an.analyse()
after_roles = {r.role: r.bone for r in after.roles}
for role, old in before_roles.items():
    want = cv.MIXAMO[role]
    if want not in arm.data.bones:
        problems.append(f"bone {old} -> {want}: not in armature")
    if after_roles.get(role) != want:
        problems.append(f"VRM humanoid {role}: says {after_roles.get(role)!r}, want {want}")
    for o in meshes:
        old_count = weights_before[o.name].get(old)
        if old_count is None:
            continue
        vg = o.vertex_groups.get(want)
        if vg is None:
            problems.append(f"{o.name}: vertex group {old} not renamed to {want}")
        elif old in o.vertex_groups:
            problems.append(f"{o.name}: old vertex group {old} still there")
        else:
            n = sum(1 for v in o.data.vertices for g in v.groups if g.group == vg.index)
            if n != old_count:
                problems.append(f"{o.name}: {want} has {n} weighted vertices, had {old_count}")

after_springs = [(s.target, list(s.roots)) for s in after.springs]
if after_springs != before_springs:
    problems.append(f"spring chains changed: {before_springs[:2]} -> {after_springs[:2]}")
if len(set(after_roles.values())) != len(after_roles):
    problems.append("two roles share a bone name")

bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")
with open(out, "rb") as f:
    data = f.read()
gltf = json.loads(data[20:20 + struct.unpack_from("<I", data, 12)[0]])
node_names = {n.get("name") for n in gltf["nodes"]}
joints = {gltf["nodes"][j].get("name") for s in gltf.get("skins", []) for j in s["joints"]}
missing = [cv.MIXAMO[r] for r in before_roles if cv.MIXAMO[r] not in node_names]
if missing:
    problems.append(f"GLB lacks nodes {missing[:5]}")
if not {"Hips", "Head", "LeftHand"} <= joints:
    problems.append("GLB skin joints lack Mixamo names")

print(f"renamed roles: {len(before_roles)}; meshes checked: {[o.name for o in meshes]}")
print("sample:", [(before_roles[r], cv.MIXAMO[r]) for r in ("hips", "leftupperarm", "leftthumbmetacarpal", "head")])
for p in problems:
    print("!!", p)
print(f"RESULT: {len(problems)} problem(s)")
