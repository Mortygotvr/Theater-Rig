"""Headless test of contact frames: two animated objects ("Pie Throw" over
frames 1-30 and "Spin" over 1-20). Timeline markers "contact" (10) and
"Contact 2" (25) are Pie Throw's; "other" (12) isn't a contact and "contact"
at 40 is past its end; Spin has its own pose marker "contact" (5). The GLB's
animations carry them as extras, theater_contacts, in seconds from each
animation's first frame.

blender --background --python tests/run_contacts.py -- <out.glb>
"""

import json
import struct
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1:][0]
bpy.ops.wm.read_factory_settings(use_empty=True)
# Enabled as Blender enables it: the exporter only calls enabled add-ons' hooks
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
scene = bpy.context.scene
scene.render.fps, scene.render.fps_base = 24, 1.0


def animated(name, action_name, frames):
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.object
    obj.name = name
    for f, x in frames:
        obj.location.x = x
        obj.keyframe_insert("location", frame=f)
    obj.animation_data.action.name = action_name
    return obj.animation_data.action


pie = animated("Pie", "Pie Throw", [(1, 0.0), (30, 3.0)])
spin = animated("Spinner", "Spin", [(1, 0.0), (20, 1.0)])
for name, frame in [("contact", 10), ("Contact 2", 25), ("other", 12), ("contact", 40)]:
    scene.timeline_markers.new(name, frame=frame)
spin.pose_markers.new("contact").frame = 5

bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")
with open(out, "rb") as f:
    data = f.read()
n = struct.unpack("<I", data[12:16])[0]
gltf = json.loads(data[20:20 + n])
got = {a.get("name"): (a.get("extras") or {}).get("theater_contacts") for a in gltf.get("animations", [])}
print("contacts:", got)

problems = []
want = {"Pie Throw": [9 / 24, 24 / 24], "Spin": [4 / 24]}
for name, times in want.items():
    have = got.get(name)
    if have is None or len(have) != len(times) or any(abs(a - b) > 1e-4 for a, b in zip(have, times)):
        problems.append(f"{name}: {have}, not {times}")
print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
