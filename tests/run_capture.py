"""Headless test of Capture Image: a jar (an open cylinder with thick walls)
and a small cube at its top right (+X, +Z). Add Capture Plane faces the front
view over them. Silhouette: the jar filled, the cube top right of the picture
(not flipped). Cross-section through the jar's middle: its two walls and its
bottom, hollow inside, open at the top. Both saved as PNGs and read back.

blender --background --python tests/run_capture.py -- <out dir>
"""

import os
import sys

import bmesh
import bpy
import numpy as np

outdir = sys.argv[sys.argv.index("--") + 1:][0]
os.makedirs(outdir, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.theater_rig")
cap = sys.modules["bl_ext.user_default.theater_rig.capture"]
problems = []

# The jar: radius 0.5, 1 high (z 0..1), no top, walls 0.06 thick (Solidify)
bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=0.5, radius2=0.5, depth=1.0)
top = [f for f in bm.faces if f.normal.z > 0.9]
bmesh.ops.delete(bm, geom=top, context="FACES")
me = bpy.data.meshes.new("Jar")
bm.to_mesh(me)
bm.free()
jar = bpy.data.objects.new("Jar", me)
bpy.context.collection.objects.link(jar)
jar.location = (0, 0, 0.5)
sol = jar.modifiers.new("Solidify", "SOLIDIFY")
sol.thickness = 0.06
sol.offset = -1.0

bpy.ops.mesh.primitive_cube_add(size=0.1, location=(0.6, 0, 1.05))
cube = bpy.context.active_object
cube.name = "Marker"

for o in bpy.context.view_layer.objects:
    o.select_set(o in (jar, cube))
plane = cap.add_plane(bpy.context)
print("plane", tuple(round(v, 3) for v in plane.location), tuple(round(v, 3) for v in plane.scale))

# The plane is the active one; the meshes: every visible one (none selected besides it)
mask, objs = cap.capture(bpy.context, plane, "SILHOUETTE", 400)
h, w = mask.shape
print("silhouette", w, h, "from", sorted(o.name for o in objs), "filled", round(mask.mean(), 3))
ys, xs = np.nonzero(mask)
# The marker: the rightmost and topmost set pixels are its
cube_px = [(x, y) for x, y in zip(xs, ys) if x > w * 0.85]
if not cube_px or min(y for _, y in cube_px) > h * 0.2:
    problems.append(f"the cube isn't top right: {cube_px[:3]}")
if not mask[h // 2, w // 2]:
    problems.append("silhouette: the jar's middle isn't filled")
cap.save_png(mask, os.path.join(outdir, "silhouette.png"))

# Cross-section: only the jar (selected), the plane active
for o in bpy.context.view_layer.objects:
    o.select_set(o in (jar, plane))
bpy.context.view_layer.objects.active = plane
mask, objs = cap.capture(bpy.context, plane, "SECTION", 400, 6.0)
h, w = mask.shape
print("section", w, h, "from", sorted(o.name for o in objs))
row = mask[h // 2]
cols = np.nonzero(row)[0]
print("  middle row set at", cols.min() if cols.size else None, "…", cols.max() if cols.size else None, "count", cols.size)
if [o.name for o in objs] != ["Jar"]:
    problems.append(f"meshes: {[o.name for o in objs]}, not the jar alone")
if mask[h // 2, w // 2]:
    problems.append("section: the jar's inside isn't hollow")
# The jar spans x -0.5..0.5 on a plane widened by the marker: where its walls are
x0 = plane.location.x - plane.scale.x / 2
edge = lambda x: (x - x0) / plane.scale.x * w
print("  walls expected at", round(edge(-0.5)), "and", round(edge(0.5)))
if cols.size == 0 or abs(cols.min() - edge(-0.5)) > 4 or abs(cols.max() - edge(0.5)) > 4:
    problems.append("section: the walls aren't at the sides")
mid_col = mask[:, w // 2]
set_rows = np.nonzero(mid_col)[0]
print("  middle column set at rows", set_rows.min() if set_rows.size else None, "…", set_rows.max() if set_rows.size else None)
if set_rows.size == 0 or set_rows.min() < h * 0.8:
    problems.append("section: no bottom only (the middle column should be set at the bottom alone: open top)")
path = os.path.join(outdir, "section.png")
cap.save_png(mask, path, (0.2, 0.6, 1.0))

# Read back: the same picture, top row first
img = bpy.data.images.load(path)
px = np.array(img.pixels[:]).reshape(img.size[1], img.size[0], 4)[::-1]
back = px[:, :, 3] > 0.5
if back.shape != mask.shape or (back != mask).any():
    problems.append("the PNG read back isn't the picture")
print("PNG", img.size[:], "colour", px[back][0][:3].round(2) if back.any() else None)

# The glass picture: the jar rendered with a glass material, the walls its
# most opaque part, the rest lighter; the scene's settings as they were
mat = bpy.data.materials.new("Glass")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Transmission Weight"].default_value = 1.0
bsdf.inputs["Roughness"].default_value = 0.05
jar.data.materials.append(mat)
scene = bpy.context.scene
before = (scene.render.engine, scene.camera, scene.world, scene.render.resolution_x, len(bpy.data.objects), len(bpy.data.cameras))
w, h = cap.picture_size(plane, 160)
walls, objs = cap.capture(bpy.context, plane, "SECTION", 160, 6.0)
seen = cap.render_view(bpy.context, plane, objs, w, h, 4, "forest")
glass = cap.glass_picture(seen, walls)
a = glass[:, :, 3]
print("glass", glass.shape, "render alpha in the jar's middle", round(float(seen[h // 2, w // 2, 3]), 3),
      "walls min", round(float(a[walls].min()), 3), "rest max", round(float(a[~walls].max()), 3))
if glass.shape[:2] != (h, w):
    problems.append(f"glass picture {glass.shape[:2]}, not {(h, w)}")
if a[walls].min() < cap.WALL_ALPHA - 1e-3 or a[~walls].max() > cap.BODY_ALPHA + 1e-3:
    problems.append("glass picture: the walls aren't the most opaque part")
if seen[..., 3].max() < 0.05:
    problems.append("the render shows nothing")
after = (scene.render.engine, scene.camera, scene.world, scene.render.resolution_x, len(bpy.data.objects), len(bpy.data.cameras))
if after != before:
    problems.append(f"the scene wasn't put back: {before} -> {after}")
# What Scene's threshold keeps: the walls alone
kept = a * 255 >= cap.GLASS_THRESHOLD
if (kept != walls).any():
    problems.append("Scene's threshold doesn't keep exactly the walls")
cap.save_rgba(glass, os.path.join(outdir, "glass.png"))

# A plane cutting nothing: an empty picture
plane.location.z = 5
mask, _ = cap.capture(bpy.context, plane, "SECTION", 100)
if mask.any():
    problems.append("a plane above everything cut something")

print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
