"""Headless test of the spring preview: a VRM's springs renamed, then swung
as Theater Puppet swings them: they settle, lag when the body turns, have a
head collider, and go back as they were when it stops.

blender --background --python tests/run_spring_preview.py -- <model.vrm>
"""

import importlib.util
import math
import os
import sys

import bpy

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
springs = sys.modules["theater_rig.springs"]
sp = sys.modules["theater_rig.spring_preview"]

bpy.ops.import_scene.vrm(filepath=src)
rename.rename_to_mixamo(bpy.context)
springs.rename_springs(bpy.context)
arm = an.find_armature()
problems = []

chains = sp.roots(arm)
p = sp.Preview(arm)
print(f"{len(chains)} chain(s), {len(p.joints)} joint(s), {len(p.colliders)} collider(s): {[c[0] for c in p.colliders]}")
if not chains or not p.joints:
    problems.append("no spring chains")
if not any(c[0] == "Head" for c in p.colliders):
    problems.append("no head collider")
# A hair chain's last bone: its tail is what swings most
hair = [j for j in p.joints if j.name.startswith("spring_hair_")] or p.joints
tip = max(hair, key=lambda j: int(j.name.rsplit("_", 1)[1]))
before = {j.name: arm.pose.bones[j.name].matrix_basis.copy() for j in p.joints}


def frame(dt=1.0 / 60.0):
    bpy.context.view_layer.update()
    p.step(dt)
    bpy.context.view_layer.update()


# Settles: two seconds still, then it barely moves
for _ in range(120):
    frame()
settled = tip.tail.copy()
frame()
still = (tip.tail - settled).length
print(f"{tip.name}: settled, then {still:.5f} m in a frame")
if still > 0.002:
    problems.append(f"still moving {still:.4f}")

# The body turns 60 degrees (the whole armature, through its matrix: its
# rotation may be a quaternion): the tip swings, then settles
from mathutils import Matrix
start = arm.matrix_world.copy()
lag = 0.0
for f in range(40):
    arm.matrix_world = Matrix.Rotation(math.radians(60.0) * min(f / 10.0, 1.0), 4, "Z") @ start
    bpy.context.view_layer.update()
    p.step(1.0 / 60.0)
    bpy.context.view_layer.update()
    lag = max(lag, (tip.tail - tip.prev_tail).length)
print(f"tip moved up to {lag:.4f} m in a frame while turning")
if lag < 0.002:
    problems.append("the springs don't swing")
for _ in range(180):
    frame()
moving = (tip.tail - tip.prev_tail).length
print(f"after turning, settled again: {moving:.5f} m in a frame")
if moving > 0.002:
    problems.append("doesn't settle after the turn")

# The bones are posed (not at rest), and go back when it stops
posed = sum(1 for j in p.joints if arm.pose.bones[j.name].matrix_basis != before[j.name])
p.stop()
back = all(arm.pose.bones[n].matrix_basis == m for n, m in before.items())
print(f"{posed} bone(s) posed by the preview; put back: {back}")
if posed == 0:
    problems.append("no bone was posed")
if not back:
    problems.append("the bones weren't put back")

# The panel's button: starts (a timer), and stops putting the bones back
bpy.context.view_layer.objects.active = arm
bpy.ops.theater_rig.spring_preview()
started = sp.running() and bpy.app.timers.is_registered(sp._tick)
sp.PREVIEW.step(1.0 / 60.0)
bpy.ops.theater_rig.spring_preview()
stopped = not sp.running() and not bpy.app.timers.is_registered(sp._tick)
back = all(arm.pose.bones[n].matrix_basis == m for n, m in before.items())
print(f"button: started {started}, stopped {stopped}, bones back {back}")
if not (started and stopped and back):
    problems.append("the button doesn't start and stop it cleanly")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
