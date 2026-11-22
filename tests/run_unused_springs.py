"""Headless test of Delete Unused Spring Chains: a VRM's springs renamed, plus
a "tail" chain that bends nothing (no weights), with an accessory bone
hanging off it and an empty vertex group named after it on the body. The
button deletes that chain only (the VRM's chains bend the mesh), moves the
accessory to the chain's parent, removes the empty group and the tail kind's
settings (and those of any kind left empty), keeps the others'; the end bones
without weight are kept. (On test.vrm the hair is weighted to the head: its
chains bend nothing, only the bust's do.)

blender --background --python tests/run_unused_springs.py -- <model.vrm>
"""

import importlib.util
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = sys.argv[sys.argv.index("--") + 1:][0]

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

bpy.ops.import_scene.vrm(filepath=src)
rename.rename_to_mixamo(bpy.context)
arm = an.find_armature()
bpy.context.view_layer.objects.active = arm
bpy.ops.theater_rig.rename_springs()
problems = []
real = [r.name for r in sp.roots(arm)]
# Counted here, apart from the add-on: the chains with a weight on a mesh
counted = set()
for o in bpy.context.view_layer.objects:
    if o.type == "MESH":
        for v in o.data.vertices:
            for g in v.groups:
                if g.weight > 0:
                    counted.add(o.vertex_groups[g.group].name)
in_use = [r for r in real if any(n.startswith(sp.chain_of(r)[0] + "_") for n in counted)]
idle = sorted(sp.chain_of(r)[0] for r in real if r not in in_use)
print("chains in use:", len(in_use), "| bending nothing already:", len(idle))
if not in_use:
    problems.append("no chain in use on this model: nothing to check that it's kept")

# A chain that bends nothing, under the head, with an accessory bone off it
bpy.ops.object.mode_set(mode="EDIT")
ebs = arm.data.edit_bones
head = ebs["Head"]
prev = head
for i in range(3):
    eb = ebs.new(f"spring_tail_1_{i}")
    eb.head = head.tail + Vector((0, 0.05 * i, 0))
    eb.tail = eb.head + Vector((0, 0.05, 0))
    eb.parent = prev
    prev = eb
acc = ebs.new("Accessory")
acc.head, acc.tail = prev.tail, prev.tail + Vector((0, 0, 0.03))
acc.parent = ebs["spring_tail_1_1"]
bpy.ops.object.mode_set(mode="OBJECT")
sp.ensure_settings(arm)
body = next(o for o in bpy.context.view_layer.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers))
body.vertex_groups.new(name="spring_tail_1_0")

chains, ends = sp.unused(arm)
print("unused:", chains, "| end bones without weight kept:", ends)
if sorted(chains) != sorted(idle + ["spring_tail_1"]):
    problems.append(f"unused: {chains}, not {idle + ['spring_tail_1']}")

# The button (its execute: the confirmation is the window's)
bpy.ops.theater_rig.delete_unused_springs("EXEC_DEFAULT")
bones = arm.data.bones
if any(b.name.startswith("spring_tail_") for b in bones):
    problems.append("the unused chain's bones are still there")
left = [r.name for r in sp.roots(arm)]
if left != in_use:
    problems.append(f"chains left: {left}, not the ones in use {in_use}")
if bones["Accessory"].parent is None or bones["Accessory"].parent.name != "Head":
    problems.append(f"the accessory hangs off {bones['Accessory'].parent.name if bones['Accessory'].parent else None}, not Head")
if "spring_tail_1_0" in body.vertex_groups:
    problems.append("the empty vertex group is still there")
gone_kinds = {"tail"} | {sp.kind_of(r) for r in real} - {sp.kind_of(r) for r in in_use}
if any(k.startswith(f"spring_{g}_") for g in gone_kinds for k in arm.data.keys()):
    problems.append(f"settings of kinds left with no chain are still there: {gone_kinds}")
if not sp.grouped(arm):
    problems.append("the kinds still there lost their settings")
print("chains now:", len(left), "| accessory parent:", bones["Accessory"].parent.name)

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
