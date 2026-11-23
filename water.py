"""Make Water: a liquid filling a container, for Theater Puppet (its water.rs).

The liquid is the container's inside, closed: its inner wall and a lid. In
Puppet, everything above its level lies flat onto it (at any level its sides
fit the walls, its top is the surface) and the surface moves with waves.

From the container's inner wall faces selected in Edit Mode: they're copied
into a new object, the top closed with a lid fine enough for waves, the
normals turned outward and the surface pulled in a little (not flickering
against the glass). On a mesh of your own (Object Mode): it's marked as is.

Either way: its rotation and scale applied (Puppet's up is the mesh's own),
the shape key `water_empty` (0 full, 1 empty: animate it from 1 to 0 to fill
it), and a material (a see-through blue if it has none) carrying the waves:
custom property `theater_water` {height, size, speed}, exported as its extras."""

import bmesh
import bpy

EMPTY_KEY = "water_empty"
PROP = "theater_water"


def _lid(bm, cuts=6):
    """The open borders closed, each with a lid fine enough to bend."""
    edges = [e for e in bm.edges if e.is_boundary]
    if not edges:
        return
    made = bmesh.ops.holes_fill(bm, edges=edges, sides=0)["faces"]
    for f in list(made):
        if not f.is_valid:
            continue
        poked = bmesh.ops.poke(bm, faces=[f])["faces"]
        inner = {e for p in poked for e in p.edges}
        bmesh.ops.subdivide_edges(bm, edges=list(inner), cuts=cuts, use_grid_fill=True)


def from_faces(context, inset=0.0005, cuts=6):
    """The selected faces of the mesh in Edit Mode, as a closed liquid of its own."""
    src = context.edit_object
    bpy.ops.object.mode_set(mode="OBJECT")
    selected = [p.index for p in src.data.polygons if p.select]
    if not selected:
        bpy.ops.object.mode_set(mode="EDIT")
        raise ValueError("Select the container's inner wall faces first")
    bm = bmesh.new()
    bm.from_mesh(src.data)
    bm.faces.ensure_lookup_table()
    keep = {bm.faces[i] for i in selected}
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f not in keep], context="FACES")
    # The inner wall faces inward (into the hollow): the liquid's skin faces out
    bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
    _lid(bm, cuts)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.normal_update()
    # A little inside the glass
    for v in bm.verts:
        v.co -= v.normal * inset
    me = bpy.data.meshes.new("Water")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Water", me)
    for c in src.users_collection:
        c.objects.link(ob)
    ob.matrix_world = src.matrix_world.copy()
    ob.parent = src.parent
    if src.parent is not None:
        ob.matrix_parent_inverse = src.matrix_parent_inverse.copy()
    for o in context.view_layer.objects:
        o.select_set(o == ob)
    context.view_layer.objects.active = ob
    return ob


def water_material(height, size, speed):
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


def mark(context, ob, height=0.004, size=0.06, speed=0.8):
    """`ob` as a liquid: rotation and scale applied, its empty key, its waves."""
    if ob.type != "MESH":
        raise ValueError(f"{ob.name} isn't a mesh")
    for o in context.view_layer.objects:
        o.select_set(o == ob)
    context.view_layer.objects.active = ob
    if ob.data.users == 1:
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if ob.data.shape_keys is None:
        ob.shape_key_add(name="Basis", from_mix=False)
    keys = ob.data.shape_keys.key_blocks
    if EMPTY_KEY not in keys:
        ob.shape_key_add(name=EMPTY_KEY, from_mix=False)
    keys[EMPTY_KEY].value = 0.0
    keys[EMPTY_KEY].slider_max = 1.0
    if not ob.data.materials or ob.data.materials[0] is None:
        mat = water_material(height, size, speed)
        if ob.data.materials:
            ob.data.materials[0] = mat
        else:
            ob.data.materials.append(mat)
    for mat in ob.data.materials:
        if mat is not None:
            mat[PROP] = {"height": float(height), "size": float(size), "speed": float(speed)}
    return ob


class THEATERRIG_OT_make_water(bpy.types.Operator):
    """A liquid filling a container, for Theater Puppet. In Edit Mode: from the container's inner
    wall faces selected (copied, closed with a lid, a little inside the glass). In Object Mode: the
    selected mesh as is. Puppet lays its top onto its level (fitting the walls) and moves the
    surface with waves; its shape key water_empty empties it (animate it from 1 to 0 to fill)"""

    bl_idname = "theater_rig.make_water"
    bl_label = "Make Water"
    bl_options = {"REGISTER", "UNDO"}

    height: bpy.props.FloatProperty(name="Wave height (mm)", default=4.0, min=0.0, max=500.0)
    size: bpy.props.FloatProperty(name="Wave length (cm)", default=6.0, min=0.1, max=1000.0)
    speed: bpy.props.FloatProperty(name="Waves a second", default=0.8, min=0.0, max=10.0)
    inset: bpy.props.FloatProperty(name="Inside the glass by (mm)", default=0.5, min=0.0, max=50.0, description="From faces: how far in from the glass")
    cuts: bpy.props.IntProperty(name="Lid detail", default=6, min=1, max=40, description="From faces: how fine the lid (the waves bend it)")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            if context.mode == "EDIT_MESH":
                ob = from_faces(context, self.inset / 1000.0, self.cuts)
            else:
                ob = context.active_object
                if ob is None:
                    raise ValueError("Select the liquid's mesh, or the container's inner faces in Edit Mode")
            mark(context, ob, self.height / 1000.0, self.size / 100.0, self.speed)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{ob.name} is water: animate its shape key {EMPTY_KEY} from 1 (empty) to 0 (full) to fill it")
        return {"FINISHED"}


CLASSES = (THEATERRIG_OT_make_water,)
