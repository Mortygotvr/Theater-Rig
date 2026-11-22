"""Headless test of Mixamo's DAE in Rig (Blender 5 reads no Collada: dae.py):
the With Skin DAE imported as a skeleton at its T-pose (arms level, hips at
Mixamo's height) moving as the FBX of the same animation does (compared from
the end: the downloads may be trimmed differently); Convert makes its GLB;
the Without Skin DAE is refused, saying so.

blender --background --python tests/run_dae.py -- <with skin.dae> <same.fbx> <out dir> [<without skin.dae>]
"""

import os
import shutil
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
dae, fbx, outdir = args[:3]
noskin = args[3] if len(args) > 3 else None
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
problems = []

shutil.rmtree(outdir, ignore_errors=True)
os.makedirs(outdir)
d = os.path.join(outdir, "From Dae.dae")
f = os.path.join(outdir, "From Fbx.fbx")
shutil.copy(dae, d)
shutil.copy(fbx, f)

for p in (d, f):
    if bpy.ops.theater_rig.import_mixamo("EXEC_DEFAULT", filepath=p) != {"FINISHED"}:
        problems.append(f"import {p}")
a, b = bpy.data.objects.get("From Dae"), bpy.data.objects.get("From Fbx")
if a is None or b is None:
    print("PROBLEMS:", *problems, "skeletons missing", sep="\n  ")
    raise SystemExit
# T-pose at rest
W = a.matrix_world
la = a.data.bones["LeftArm"]
arm_dir = (W.to_3x3() @ la.matrix_local.to_3x3().col[1]).normalized()
hips = (W @ a.data.bones["Hips"].head_local).z
print("DAE rest: left arm along", tuple(round(x, 2) for x in arm_dir), "| hips %.3f m" % hips)
if arm_dir.x < 0.99 or abs(hips - 1.043) > 0.01:
    problems.append("the DAE's skeleton isn't Mixamo's T-pose")

# The same motion as the FBX's, frame by frame from the end
scene = bpy.context.scene
fa = [int(x) for x in a.animation_data.action.frame_range]
fb = [int(x) for x in b.animation_data.action.frame_range]
print("frames: DAE", fa, "FBX", fb)
worst = (0.0, "", 0)
for k in range(0, fa[1] - fa[0] + 1, 3):
    scene.frame_set(fa[1] - k)
    pa = {n: (a.matrix_world @ a.pose.bones[n].head) for n in ("Head", "LeftHand", "RightFoot", "Hips")}
    scene.frame_set(fb[1] - k)
    for n, p in pa.items():
        e = (p - (b.matrix_world @ b.pose.bones[n].head)).length
        if e > worst[0]:
            worst = (e, n, k)
print("furthest from the FBX's: %.4f m (%s, %d frames from the end)" % worst)
if worst[0] > 0.01:
    problems.append("the DAE doesn't move as the FBX")

# Convert
out = os.path.join(outdir, "From Dae.glb")
os.remove(d.replace(".dae", ".glb")) if os.path.exists(out) else None
if bpy.ops.theater_rig.convert_mixamo("EXEC_DEFAULT", filepath=d) != {"FINISHED"} or not os.path.exists(out):
    problems.append("Convert of the DAE")

# Without skin: refused
if noskin:
    ns = os.path.join(outdir, "No Skin.dae")
    shutil.copy(noskin, ns)
    before = set(bpy.data.objects)
    res = bpy.ops.theater_rig.import_mixamo("EXEC_DEFAULT", filepath=ns)
    print("without skin:", res)
    if res != {"CANCELLED"} or set(bpy.data.objects) != before:
        problems.append("a DAE without skin was imported")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
