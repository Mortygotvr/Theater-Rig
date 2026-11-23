"""Capture Image: a plane says where a picture of the scene is taken, and the
picture is saved as a PNG for Theater Scene (a target's hitbox, or a border
its liquid fills: a jar's walls).

The plane (any mesh: its flat face) faces the way the picture looks; the
picture covers it exactly, its up the plane's local Y, its right its X. Two
kinds:

- Silhouette: every mesh flattened onto the plane, filled (a hitbox).
- Cross-section: where the plane cuts the meshes, drawn as lines so thick
  (a border: through a jar's middle, its two walls and its bottom, hollow
  inside, open at the top).

The meshes: those selected besides the plane, else every visible one. As they
are now (modifiers, pose, the frame). Drawn here, not rendered: exact, no
camera or render settings."""

import os

import bpy
import numpy as np
from mathutils import Matrix

NAME = "Capture Plane"


def plane_frame(plane):
    """The plane's picture: (world to plane space, its x range, its y range),
    the plane space its local one with the scale kept (sizes in metres)."""
    loc, rot, scale = plane.matrix_world.decompose()
    to_world = Matrix.LocRotScale(loc, rot, None)
    xs = [v.co.x * scale.x for v in plane.data.vertices]
    ys = [v.co.y * scale.y for v in plane.data.vertices]
    if not xs or max(xs) - min(xs) < 1e-6 or max(ys) - min(ys) < 1e-6:
        raise ValueError(f"{plane.name} has no flat face to take the picture on")
    return to_world.inverted(), (min(xs), max(xs)), (min(ys), max(ys))


def meshes_for(context, plane):
    sel = [o for o in context.selected_objects if o.type == "MESH" and o != plane]
    if sel:
        return sel
    return [o for o in context.view_layer.objects if o.type == "MESH" and o != plane and o.visible_get()]


def triangles(context, objects, to_plane):
    """Every triangle of `objects` as evaluated now, in plane space: (n, 3, 3)."""
    deps = context.evaluated_depsgraph_get()
    out = []
    for o in objects:
        ev = o.evaluated_get(deps)
        me = ev.to_mesh()
        try:
            me.calc_loop_triangles()
            n = len(me.loop_triangles)
            if not n:
                continue
            co = np.empty(len(me.vertices) * 3, dtype=np.float64)
            me.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3)
            idx = np.empty(n * 3, dtype=np.int64)
            me.loop_triangles.foreach_get("vertices", idx)
            m = np.array(to_plane @ ev.matrix_world)
            pts = co @ m[:3, :3].T + m[:3, 3]
            out.append(pts[idx.reshape(-1, 3)])
        finally:
            ev.to_mesh_clear()
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


def _to_pixels(xy, xr, yr, w, h):
    """Plane x, y to pixel x, y (y down: the picture's top is the plane's +Y)."""
    px = (xy[..., 0] - xr[0]) / (xr[1] - xr[0]) * w
    py = (yr[1] - xy[..., 1]) / (yr[1] - yr[0]) * h
    return np.stack([px, py], axis=-1)


def silhouette(tris, xr, yr, w, h):
    """Every triangle flattened onto the plane, filled: a mask (h, w)."""
    mask = np.zeros((h, w), dtype=bool)
    pix = _to_pixels(tris[:, :, :2], xr, yr, w, h)
    for t in pix:
        x0, y0 = np.floor(t.min(axis=0)).astype(int)
        x1, y1 = np.ceil(t.max(axis=0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if x0 >= x1 or y0 >= y1:
            continue
        if x1 - x0 == 1 and y1 - y0 == 1:
            mask[y0, x0] = True
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        (ax, ay), (bx, by), (cx, cy) = t
        d1 = (gx - bx) * (ay - by) - (ax - bx) * (gy - by)
        d2 = (gx - cx) * (by - cy) - (bx - cx) * (gy - cy)
        d3 = (gx - ax) * (cy - ay) - (cx - ax) * (gy - ay)
        neg = (d1 < 0) | (d2 < 0) | (d3 < 0)
        pos = (d1 > 0) | (d2 > 0) | (d3 > 0)
        mask[y0:y1, x0:x1] |= ~(neg & pos)
    return mask


def section_segments(tris):
    """Where the plane (z = 0) cuts the triangles: segments (n, 2, 2) in plane x, y."""
    z = tris[:, :, 2]
    out = []
    for t, d in zip(tris, z):
        pts = []
        for i, j in ((0, 1), (1, 2), (2, 0)):
            if (d[i] < 0) != (d[j] < 0):
                f = d[i] / (d[i] - d[j])
                pts.append(t[i, :2] + (t[j, :2] - t[i, :2]) * f)
        if len(pts) == 2:
            out.append(pts)
    return np.array(out).reshape(-1, 2, 2)


def cross_section(tris, xr, yr, w, h, thickness):
    """Where the plane cuts the triangles, as lines `thickness` pixels wide."""
    mask = np.zeros((h, w), dtype=bool)
    r = max(thickness, 1.0) / 2.0
    for a, b in _to_pixels(section_segments(tris), xr, yr, w, h):
        x0, y0 = np.floor(np.minimum(a, b) - r).astype(int)
        x1, y1 = np.ceil(np.maximum(a, b) + r).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if x0 >= x1 or y0 >= y1:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        ab = b - a
        ll = float(ab @ ab)
        t = np.clip(((gx - a[0]) * ab[0] + (gy - a[1]) * ab[1]) / ll, 0.0, 1.0) if ll > 1e-12 else np.zeros_like(gx)
        dx, dy = gx - (a[0] + ab[0] * t), gy - (a[1] + ab[1] * t)
        mask[y0:y1, x0:x1] |= dx * dx + dy * dy <= r * r
    return mask


def capture(context, plane, kind="SILHOUETTE", width=1024, thickness=6.0):
    """The picture on `plane`: (mask (h, w) bool, meshes used)."""
    # Where everything is now (a plane just moved or sized isn't, until then)
    context.view_layer.update()
    to_plane, xr, yr = plane_frame(plane)
    w = max(int(width), 8)
    h = max(int(round(w * (yr[1] - yr[0]) / (xr[1] - xr[0]))), 8)
    objects = meshes_for(context, plane)
    tris = triangles(context, objects, to_plane)
    if kind == "SECTION":
        mask = cross_section(tris, xr, yr, w, h, thickness)
    else:
        mask = silhouette(tris, xr, yr, w, h)
    return mask, objects


def save_png(mask, path, color=(1.0, 1.0, 1.0)):
    """The mask as a PNG: `color` where it's set, transparent elsewhere."""
    h, w = mask.shape
    px = np.zeros((h, w, 4), dtype=np.float32)
    px[mask] = (color[0], color[1], color[2], 1.0)
    # Blender's images are bottom row first
    img = bpy.data.images.new("theater_capture", w, h, alpha=True)
    try:
        img.pixels.foreach_set(px[::-1].ravel())
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
    finally:
        bpy.data.images.remove(img)


def add_plane(context):
    """A capture plane facing the front view (its picture: X right, Z up)
    over the selected meshes (else every visible one), through their middle."""
    objs = [o for o in context.selected_objects if o.type == "MESH"] or [o for o in context.view_layer.objects if o.type == "MESH" and o.visible_get()]
    pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    if pts:
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
    else:
        lo, hi = [-1.0] * 3, [1.0] * 3
    mid = [(lo[i] + hi[i]) / 2 for i in range(3)]
    size_x = (hi[0] - lo[0]) * 1.1 or 2.0
    size_z = (hi[2] - lo[2]) * 1.1 or 2.0
    me = bpy.data.meshes.new(NAME)
    me.from_pydata([(-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new(NAME, me)
    context.collection.objects.link(ob)
    # Its face toward the front view (-Y), its up world Z
    ob.rotation_euler = (np.pi / 2, 0.0, 0.0)
    ob.location = mid
    ob.scale = (size_x, size_z, 1.0)
    context.view_layer.update()
    ob.display_type = "WIRE"
    ob.hide_render = True
    ob.show_in_front = True
    for o in context.view_layer.objects:
        o.select_set(o == ob)
    context.view_layer.objects.active = ob
    return ob


class THEATERRIG_OT_add_capture_plane(bpy.types.Operator):
    """Adds a capture plane facing the front view, over the selected meshes (else every
    visible one), through their middle. Move, turn and size it: the picture covers it,
    looking the way its face points"""

    bl_idname = "theater_rig.add_capture_plane"
    bl_label = "Add Capture Plane"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        ob = add_plane(context)
        self.report({"INFO"}, f"Added {ob.name}: place it, then Save Capture Image with it active")
        return {"FINISHED"}


class THEATERRIG_OT_save_capture(bpy.types.Operator):
    """Saves a PNG of what the active plane sees, for Theater Scene: Silhouette (everything
    flattened onto it, filled: a hitbox) or Cross-section (where it cuts the meshes: a border,
    like a jar's walls for a liquid to fill). The meshes: those selected besides the plane,
    else every visible one, as they are now"""

    bl_idname = "theater_rig.save_capture"
    bl_label = "Save Capture Image"
    bl_options = {"REGISTER"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.png", options={"HIDDEN"})
    kind: bpy.props.EnumProperty(
        name="Kind",
        items=[
            ("SILHOUETTE", "Silhouette (hitbox)", "Everything flattened onto the plane, filled"),
            ("SECTION", "Cross-section (border)", "Where the plane cuts the meshes, as lines: a jar's walls and bottom, hollow"),
        ],
        default="SILHOUETTE",
    )
    width: bpy.props.IntProperty(name="Width (px)", default=1024, min=16, max=8192, description="The picture's width; its height follows the plane's shape")
    thickness: bpy.props.FloatProperty(name="Line (px)", default=6.0, min=1.0, max=100.0, description="Cross-section: how thick its lines")
    color: bpy.props.FloatVectorProperty(name="Colour", subtype="COLOR", size=3, min=0.0, max=1.0, default=(1.0, 1.0, 1.0))

    def invoke(self, context, event):
        plane = context.active_object
        if plane is None or plane.type != "MESH":
            self.report({"ERROR"}, "Make the capture plane active (Add Capture Plane)")
            return {"CANCELLED"}
        folder = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
        self.filepath = os.path.join(folder, plane.name.replace(" ", "_") + ".png")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "kind")
        col.prop(self, "width")
        if self.kind == "SECTION":
            col.prop(self, "thickness")
        col.prop(self, "color")

    def execute(self, context):
        plane = context.active_object
        if plane is None or plane.type != "MESH":
            self.report({"ERROR"}, "Make the capture plane active (Add Capture Plane)")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            mask, objects = capture(context, plane, self.kind, self.width, self.thickness)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if not mask.any():
            what = "cuts no mesh (put it through them)" if self.kind == "SECTION" else "sees no mesh"
            self.report({"ERROR"}, f"{plane.name} {what}: nothing saved")
            return {"CANCELLED"}
        path = bpy.path.abspath(self.filepath)
        if not path.lower().endswith(".png"):
            path += ".png"
        save_png(mask, path, self.color)
        h, w = mask.shape
        self.report({"INFO"}, f"Saved {os.path.basename(path)} ({w}x{h}) from {len(objects)} mesh(es)")
        return {"FINISHED"}


CLASSES = (THEATERRIG_OT_add_capture_plane, THEATERRIG_OT_save_capture)
