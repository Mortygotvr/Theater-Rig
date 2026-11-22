"""Headless test: Rig turned off and on in one Blender reads all its files
again (not the old ones Python kept): an old overlay.py in memory, without
over(), is replaced; the panel's Make Colour Slot check (line 592's
overlay.over) works.

blender --background --python tests/run_reload.py
"""

import os
import sys

import bpy

PKG = "bl_ext.user_default.theater_rig"
problems = []
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module=PKG)
# As if overlay.py were the old one still in memory, and a new version came
# (Blender reads Rig again when its __init__.py changed)
del sys.modules[PKG + ".overlay"].over
init = sys.modules[PKG].__file__
st = os.stat(init)
os.utime(init, (st.st_atime, st.st_mtime + 2))
bpy.ops.preferences.addon_disable(module=PKG)
bpy.ops.preferences.addon_enable(module=PKG)
ov = sys.modules[PKG + ".overlay"]
print("over() there after off and on:", hasattr(ov, "over"))
if not hasattr(ov, "over") or not hasattr(sys.modules[PKG].overlay, "over"):
    problems.append("the old overlay.py stayed")
# Make Colour Slot's check runs (a texture, no overlay)
img = bpy.data.images.new("T", 8, 8)
bpy.context.scene.theater_rig.color_image = img
try:
    [m for m in sys.modules[PKG].colour_users(img) if ov.over(m)]
except Exception as e:
    problems.append(f"the check fails: {e}")
print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
