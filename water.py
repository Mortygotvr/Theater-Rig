"""Make Water: a liquid filling a container, for Theater Puppet (its water.rs).

Select the container (a jar) and Make Water: its inside is measured (from
its upright middle line, rays out to its inner wall all around, at many
heights, and one down to its inner floor) and a Water object is built to
fit it, a little inside the glass: rings up its walls (its neck, its belly,
whatever its shape) and a fine lid on top for the waves. The container
itself is never changed.

In Puppet, everything above the liquid's level lies flat onto it (at any
level its sides fit the walls, its top is the surface) and the surface moves
with waves. The level: its shape key `water_empty` (0 full, 1 empty: animate
it from 1 to 0 to fill). The waves: its material's custom property
`theater_water` {height, size, speed}, exported as its extras.

The container's up is its own Z (as it stands in Blender)."""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

EMPTY_KEY = "water_empty"
PROP = "theater_water"


def unmark(ob):
    """What an earlier Make Water put on `ob` (it took the container for the
    liquid) taken off: its water_empty key (and a lone Basis), the waves on
    its materials. True when there was some."""
    found = False
    keys = ob.data.shape_keys
    if keys is not None and EMPTY_KEY in keys.key_blocks:
        ob.shape_key_remove(keys.key_blocks[EMPTY_KEY])
        found = True
        keys = ob.data.shape_keys
        if keys is not None and len(keys.key_blocks) == 1:
            ob.shape_key_remove(keys.key_blocks[0])
    for mat in ob.data.materials:
        if mat is not None and PROP in mat:
            del mat[PROP]
            found = True
    return found


def measure(context, jar, angles=48, rings=24, inset=0.0005):
    """The jar's inside, in its own space: (rings of points up its walls,
    bottom first, each `angles` around; its floor height; its middle (x, y)).
    None when it has no inside (rays from its middle hit nothing)."""
    deps = context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(jar, deps)
    xs = [c[0] for c in jar.bound_box]
    ys = [c[1] for c in jar.bound_box]
    zs = [c[2] for c in jar.bound_box]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    z_lo, z_hi = min(zs), max(zs)
    span = z_hi - z_lo
    # Its floor: straight down its middle from its top
    # The first thing below the top: the floor (a jar's opening lets the ray
    # in); nothing under its middle (no bottom there): its lowest point
    hit = bvh.ray_cast(Vector((cx, cy, z_hi + span)), Vector((0, 0, -1)))
    floor = hit[0].z if hit[0] is not None else z_lo
    # From above the floor up: the inner wall all around, until the opening
    dirs = [Vector((math.cos(a), math.sin(a), 0.0)) for a in (i / angles * math.tau for i in range(angles))]
    out = []
    step = (z_hi - floor) / rings
    z = floor + max(inset * 2, step * 0.25)
    while z < z_hi - 1e-6:
        ring = []
        missed = 0
        for d in dirs:
            h = bvh.ray_cast(Vector((cx, cy, z)), d, span * 4)
            if h[0] is None:
                missed += 1
                ring.append(None)
            else:
                ring.append(max((h[0].xy - Vector((cx, cy))).length - inset, inset))
        if missed > angles // 4:
            break  # above its walls: the opening
        known = [r for r in ring if r is not None]
        ring = [r if r is not None else min(known) for r in ring]
        out.append((z, [Vector((cx + d.x * r, cy + d.y * r, z)) for d, r in zip(dirs, ring)]))
        z += step
    if len(out) < 2:
        return None
    return out, floor + inset, (cx, cy)


def build(rings, floor, middle, lid_steps=8):
    """The liquid's mesh from the measured rings: walls, a floor, a lid."""
    bm = bmesh.new()
    cx, cy = middle
    layers = [[bm.verts.new(p) for p in pts] for _, pts in rings]
    n = len(layers[0])
    # The floor: the lowest ring brought down onto it, closed in the middle
    bottom = [bm.verts.new((p.co.x, p.co.y, floor)) for p in layers[0]]
    layers.insert(0, bottom)
    for a, b in zip(layers, layers[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i]))
    centre = bm.verts.new((cx, cy, floor))
    for i in range(n):
        bm.faces.new((bottom[(i + 1) % n], bottom[i], centre))
    # The lid: rings closing in toward the middle, fine enough to bend
    top = layers[-1]
    z = top[0].co.z
    prev = top
    for s in range(1, lid_steps):
        k = 1.0 - s / lid_steps
        ring = [bm.verts.new((cx + (p.co.x - cx) * k, cy + (p.co.y - cy) * k, z)) for p in top]
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((prev[i], prev[j], ring[j], ring[i]))
        prev = ring
    lid_centre = bm.verts.new((cx, cy, z))
    for i in range(n):
        bm.faces.new((prev[i], prev[(i + 1) % n], lid_centre))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return bm


def water_material():
    mat = bpy.data.materials.new("Water")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.35, 0.62, 0.95, 1.0)
        bsdf.inputs["Alpha"].default_value = 0.55
        bsdf.inputs["Roughness"].default_value = 0.05
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    else:
        mat.blend_method = "BLEND"
    return mat


def make(context, jar, height=0.004, size=0.06, speed=0.8, inset=0.0005, angles=48, rings=24, lid_steps=8):
    """A Water object filling `jar`, beside it in the scene: (it, whether an
    earlier Make Water's marks were taken off the jar)."""
    if jar is None or jar.type != "MESH":
        raise ValueError("Select the container (the jar)")
    cleaned = unmark(jar)
    # Its size in its own space (a scaled jar: measured scaled)
    loc, rot, scale = jar.matrix_world.decompose()
    measured = measure(context, jar, angles, rings, inset / max(min(scale), 1e-6))
    if measured is None:
        raise ValueError(f"{jar.name} has no inside to fill: from its middle (seen from above), its walls aren't all around (openings, or it isn't upright on its Z)")
    pts, floor, middle = measured
    bm = build(pts, floor, middle, lid_steps)
    # Its points in the jar's space, scaled as the jar is: the water's own
    # space is the jar's place and turn without its scale (up: the jar's Z)
    bmesh.ops.transform(bm, matrix=Matrix.Diagonal(scale).to_4x4(), verts=bm.verts)
    me = bpy.data.meshes.new("Water")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Water", me)
    for c in jar.users_collection:
        c.objects.link(ob)
    ob.matrix_world = Matrix.LocRotScale(loc, rot, None)
    me.materials.append(water_material())
    me.materials[0][PROP] = {"height": float(height), "size": float(size), "speed": float(speed)}
    ob.shape_key_add(name="Basis", from_mix=False)
    key = ob.shape_key_add(name=EMPTY_KEY, from_mix=False)
    key.value = 0.0
    for o in context.view_layer.objects:
        o.select_set(o == ob)
    context.view_layer.objects.active = ob
    return ob, cleaned


class THEATERRIG_OT_make_water(bpy.types.Operator):
    """Select the container (a jar): a Water object is built to fill its inside (measured from
    its upright middle line), a little inside the glass, with a fine lid for waves. The container
    isn't changed. In Theater Puppet the liquid's top lies on its level (fitting the walls) and
    waves; its shape key water_empty empties it (animate it from 1 to 0 to fill)"""

    bl_idname = "theater_rig.make_water"
    bl_label = "Make Water"
    bl_options = {"REGISTER", "UNDO"}

    height: bpy.props.FloatProperty(name="Wave height (mm)", default=4.0, min=0.0, max=500.0)
    size: bpy.props.FloatProperty(name="Wave length (cm)", default=6.0, min=0.1, max=1000.0)
    speed: bpy.props.FloatProperty(name="Waves a second", default=0.8, min=0.0, max=10.0)
    inset: bpy.props.FloatProperty(name="Inside the glass by (mm)", default=0.5, min=0.0, max=50.0)
    detail: bpy.props.IntProperty(name="Detail around", default=48, min=8, max=256, description="How many points around its walls")
    rings: bpy.props.IntProperty(name="Detail up", default=24, min=2, max=200, description="How many rings up its walls (its shape)")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        jar = context.active_object
        try:
            ob, cleaned = make(context, jar, self.height / 1000.0, self.size / 100.0, self.speed, self.inset / 1000.0, self.detail, self.rings)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        note = f" (took an earlier Make Water's key and wave settings off {jar.name})" if cleaned else ""
        self.report({"INFO"}, f"{ob.name} fills {jar.name}: animate its shape key {EMPTY_KEY} from 1 (empty) to 0 (full){note}")
        return {"FINISHED"}


CLASSES = (THEATERRIG_OT_make_water,)
