"""Theater Rig: prepares VRM and GLB avatars for the Theater avatar renderer by
renaming parts to its convention (see conventions.py)."""

# Already loaded once: this is Reload Scripts (F3), so the other files reload too
_reloading = "bpy" in locals()

import os

import bpy
from bpy_extras.io_utils import ExportHelper

from . import conventions
from . import analyse as an
from . import align
from . import colour
from . import detoon
from . import export
from . import rename
from . import springs
from . import strip
from . import tiles
from . import tpose

if _reloading:
    import importlib

    # Dependencies first: conventions, then analyse, then what uses them
    for _module in (conventions, an, rename, detoon, springs, align, tpose, colour, strip, tiles, export):
        importlib.reload(_module)

REPORT_TEXT = "Theater Rig report"


class THEATERRIG_OT_rename_springs(bpy.types.Operator):
    """Renames spring chains to spring_<kind>_<n>_<i> and stores their stiffness, gravity,
    drag and radius on each chain's root bone. Undo with Ctrl+Z"""

    bl_idname = "theater_rig.rename_springs"
    bl_label = "Rename Springs"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm, chains = springs.rename_springs(context)
        if arm is None:
            self.report({"ERROR"}, "No armature")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Renamed {len(chains)} spring chain(s)")
        bpy.ops.theater_rig.analyse()
        return {"FINISHED"}


class THEATERRIG_OT_align_bones(bpy.types.Operator):
    """Points every bone at its child with one roll convention (the mesh doesn't move). Undo with Ctrl+Z"""

    bl_idname = "theater_rig.align_bones"
    bl_label = "Align Bones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm, n = align.align_bones(context)
        if arm is None:
            self.report({"ERROR"}, "No armature")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Aligned {n} bone(s)")
        return {"FINISHED"}


class THEATERRIG_OT_tpose(bpy.types.Operator):
    """Arms horizontal, legs straight, applied as the rest pose with shape keys kept.
    Nothing happens if the model is already in a T-pose. Undo with Ctrl+Z"""

    bl_idname = "theater_rig.tpose"
    bl_label = "T-Pose"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm, off = tpose.t_pose(context)
        if arm is None:
            self.report({"ERROR"}, "No armature")
            return {"CANCELLED"}
        if not off:
            self.report({"INFO"}, "Already in a T-pose: nothing changed")
        else:
            worst = max(off, key=lambda x: x[1])
            self.report({"INFO"}, f"T-posed {len(off)} bone(s) (most off: {worst[0]} by {worst[1]:.0f} deg)")
        return {"FINISHED"}


class THEATERRIG_OT_pick_texture(bpy.types.Operator):
    """Takes the base colour texture of the selected object's active material"""

    bl_idname = "theater_rig.pick_texture"
    bl_label = "Pick from Selected"
    bl_options = {"REGISTER"}

    def execute(self, context):
        img, mat = colour.image_of_selection(context)
        if img is None:
            self.report({"ERROR"}, f"No base colour texture on {mat.name if mat else 'the selection'}")
            return {"CANCELLED"}
        context.scene.theater_rig.color_image = img
        self.report({"INFO"}, f"{img.name} (from {mat.name})")
        return {"FINISHED"}


class THEATERRIG_OT_pick_tile_texture(bpy.types.Operator):
    """Takes the base colour texture of the selected object's active material"""

    bl_idname = "theater_rig.pick_tile_texture"
    bl_label = "Pick from Selected"
    bl_options = {"REGISTER"}

    def execute(self, context):
        img, mat = colour.image_of_selection(context)
        if img is None:
            self.report({"ERROR"}, f"No base colour texture on {mat.name if mat else 'the selection'}")
            return {"CANCELLED"}
        context.scene.theater_rig.tile_image = img
        self.report({"INFO"}, f"{img.name} (from {mat.name})")
        return {"FINISHED"}


class THEATERRIG_OT_make_tiles(bpy.types.Operator):
    """Splits the texture into a grid of named tiles (across then down) on every material
    using it, kept on the armature for Export. Tiles made before on those materials are
    replaced. Undo with Ctrl+Z"""

    bl_idname = "theater_rig.make_tiles"
    bl_label = "Make Tiles"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.theater_rig
        arm = an.find_armature(context)
        if arm is None:
            self.report({"ERROR"}, "No armature")
            return {"CANCELLED"}
        if st.tile_image is None:
            self.report({"ERROR"}, "Choose a texture first")
            return {"CANCELLED"}
        try:
            count, kinds = tiles.make(arm, st.tile_image, st.tile_columns, st.tile_rows, st.tile_names, st.tile_default)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        moved = [m for m, k in kinds.items() if k == "cell"]
        how = f"{len(moved)} already on one cell (moved)" if moved else ""
        shrunk = [m for m, k in kinds.items() if k == "sheet"]
        if shrunk:
            how += (", " if how else "") + f"{len(shrunk)} over the whole sheet (now showing cell {st.tile_default})"
        self.report({"INFO"}, f"{count} tile(s) on {len(kinds)} material(s): {how}")
        return {"FINISHED"}


class THEATERRIG_OT_clear_tiles(bpy.types.Operator):
    """Removes the tiles on the materials using the texture (the VRM's own come back at Export).
    Undo with Ctrl+Z"""

    bl_idname = "theater_rig.clear_tiles"
    bl_label = "Remove These Tiles"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.theater_rig
        arm = an.find_armature(context)
        if arm is None or st.tile_image is None:
            self.report({"ERROR"}, "No armature or no texture")
            return {"CANCELLED"}
        names = {m.name for m in tiles.materials_using(st.tile_image)}
        before = tiles.stored(arm)
        kept = {n: b for n, b in before.items() if not all(x["material"] in names for x in b)}
        arm[tiles.PROP] = tiles.json.dumps(kept)
        self.report({"INFO"}, f"Removed {len(before) - len(kept)} tile(s)")
        return {"FINISHED"}


class THEATERRIG_OT_make_color_slot(bpy.types.Operator):
    """Makes a greyscale copy of the texture named Color<N>; the materials using it turn
    grey, get Color<N> in their name, and keep their old colour as 'color_default'. Undo with Ctrl+Z"""

    bl_idname = "theater_rig.make_color_slot"
    bl_label = "Make Colour Slot"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.theater_rig
        if st.color_image is None:
            self.report({"ERROR"}, "Choose a texture first")
            return {"CANCELLED"}
        grey, mats = colour.make_color_slot(st.color_image, st.color_slot)
        if not mats:
            self.report({"WARNING"}, f"{grey.name} made, but no material uses {st.color_image.name} as its base colour")
        else:
            self.report({"INFO"}, f"{grey.name}: {len(mats)} material(s) follow Color{st.color_slot}")
        st.color_image = grey
        bpy.ops.theater_rig.analyse()
        return {"FINISHED"}


class THEATERRIG_OT_export(bpy.types.Operator, ExportHelper):
    """Removes the VRM colliders and VRM data, then exports the avatar as a GLB with the
    options the renderer needs (custom properties, shape keys, skin; no animation).
    Ctrl+Z brings the colliders and VRM data back"""

    bl_idname = "theater_rig.export"
    bl_label = "Export GLB"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".glb"
    filter_glob: bpy.props.StringProperty(default="*.glb", options={"HIDDEN"})

    def invoke(self, context, event):
        arm = an.find_armature(context)
        folder = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
        self.filepath = os.path.join(folder, (arm.name if arm else "avatar") + ".glb")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        arm, found, colliders, tiled = export.export_glb(context, self.filepath)
        if arm is None:
            self.report({"ERROR"}, "No armature")
            return {"CANCELLED"}
        kept = f", {tiled} tile texture expression(s) kept" if tiled else ""
        done = f"Exported {os.path.basename(self.filepath)} ({colliders} collider object(s) and the VRM data removed{kept})"
        if found:
            self.report({"WARNING"}, f"{done}, but: {'; '.join(found)}")
        else:
            self.report({"INFO"}, done)
        bpy.ops.theater_rig.analyse()
        return {"FINISHED"}


class THEATERRIG_OT_rename_mixamo(bpy.types.Operator):
    """Renames body bones to Mixamo names (vertex groups and VRM data follow). Undo with Ctrl+Z"""

    bl_idname = "theater_rig.rename_mixamo"
    bl_label = "Rename Bones (Mixamo)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm, done = rename.rename_to_mixamo(context)
        if arm is None:
            self.report({"ERROR"}, "No armature")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Renamed {len(done)} bone(s) on {arm.name}")
        bpy.ops.theater_rig.analyse()
        return {"FINISHED"}


class THEATERRIG_OT_detoonify(bpy.types.Operator):
    """Turns MToon materials into plain ones that keep their colours (shade colour as
    'shade_color'), and removes MToon outlines. Undo with Ctrl+Z"""

    bl_idname = "theater_rig.detoonify"
    bl_label = "Detoonify"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        converted, removed = detoon.detoonify()
        self.report({"INFO"}, f"Detoonified {converted} material(s), removed {removed} outline(s)")
        bpy.ops.theater_rig.analyse()
        return {"FINISHED"}


class THEATERRIG_OT_analyse(bpy.types.Operator):
    """Lists what the avatar has against the convention. Changes nothing"""

    bl_idname = "theater_rig.analyse"
    bl_label = "Analyse"
    bl_options = {"REGISTER"}

    def execute(self, context):
        rep = an.analyse(context)
        text = bpy.data.texts.get(REPORT_TEXT) or bpy.data.texts.new(REPORT_TEXT)
        text.clear()
        text.write(an.as_text(rep))
        c = rep.counts()
        st = context.scene.theater_rig
        st.analysed = True
        st.armature = rep.armature
        st.vrm = rep.vrm_spec or "plain GLB"
        st.roles, st.missing_roles = c["roles"], c["missing_roles"]
        st.springs, st.colliders = c["springs"], rep.colliders
        st.arkit_ok = c["arkit_present"] + c["arkit_exact"]
        st.arkit_approx, st.arkit_missing = c["arkit_approximate"], c["arkit_missing"]
        st.mtoon, st.outlines, st.color_slots = c["mtoon"], c["outlines"], c["color_slots"]
        self.report({"INFO"}, f"Analysed {rep.armature}: full report in the '{REPORT_TEXT}' text")
        return {"FINISHED"}


class TheaterRigState(bpy.types.PropertyGroup):
    analysed: bpy.props.BoolProperty()
    armature: bpy.props.StringProperty()
    vrm: bpy.props.StringProperty()
    roles: bpy.props.IntProperty()
    missing_roles: bpy.props.IntProperty()
    springs: bpy.props.IntProperty()
    colliders: bpy.props.IntProperty()
    arkit_ok: bpy.props.IntProperty()
    arkit_approx: bpy.props.IntProperty()
    arkit_missing: bpy.props.IntProperty()
    mtoon: bpy.props.IntProperty()
    outlines: bpy.props.IntProperty()
    color_slots: bpy.props.IntProperty()
    color_image: bpy.props.PointerProperty(type=bpy.types.Image, name="Texture")
    color_slot: bpy.props.IntProperty(name="Slot", min=0, max=99)
    tile_image: bpy.props.PointerProperty(type=bpy.types.Image, name="Texture")
    tile_columns: bpy.props.IntProperty(name="Columns", min=1, max=64, default=2)
    tile_rows: bpy.props.IntProperty(name="Rows", min=1, max=64, default=2)
    tile_names: bpy.props.StringProperty(name="Names", description="The tiles' names, comma-separated, across then down (a blank one: <texture>_<cell>)")
    tile_default: bpy.props.IntProperty(name="Default cell", min=0, description="The cell showing when no tile is on (only for a mesh whose UVs cover the whole sheet)")


class THEATERRIG_PT_panel(bpy.types.Panel):
    bl_label = "Theater Rig"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Theater Rig"

    def draw(self, context):
        lay = self.layout
        lay.operator(THEATERRIG_OT_analyse.bl_idname, icon="VIEWZOOM")
        st = context.scene.theater_rig
        if not st.analysed:
            lay.label(text="Select the avatar, then Analyse.")
            return
        col = lay.column(align=True)
        col.label(text=f"{st.armature} ({st.vrm})", icon="ARMATURE_DATA")
        warn = lambda bad: "ERROR" if bad else "CHECKMARK"
        col.label(text=f"Bone roles: {st.roles}, missing {st.missing_roles}", icon=warn(st.missing_roles))
        col.label(text=f"Spring chains: {st.springs}, collider groups: {st.colliders}", icon="FORCE_WIND")
        col.label(text=f"ARKit: {st.arkit_ok} ready, {st.arkit_approx} approximate", icon="SHAPEKEY_DATA")
        col.label(text=f"ARKit missing: {st.arkit_missing} of 52", icon=warn(st.arkit_missing))
        col.label(text=f"MToon materials: {st.mtoon}, outlines: {st.outlines}", icon="MATERIAL")
        col.label(text=f"Colour slots: {st.color_slots}", icon="COLOR")
        lay.label(text=f"Details: Text editor > '{REPORT_TEXT}'")
        lay.separator()
        lay.operator(THEATERRIG_OT_detoonify.bl_idname, icon="SHADING_SOLID")
        lay.operator(THEATERRIG_OT_rename_mixamo.bl_idname, icon="BONE_DATA")
        lay.operator(THEATERRIG_OT_rename_springs.bl_idname, icon="FORCE_WIND")
        lay.operator(THEATERRIG_OT_align_bones.bl_idname, icon="ORIENTATION_GIMBAL")
        lay.operator(THEATERRIG_OT_tpose.bl_idname, icon="ARMATURE_DATA")
        box = lay.box()
        box.label(text="Colour slot", icon="COLOR")
        box.operator(THEATERRIG_OT_pick_texture.bl_idname, icon="EYEDROPPER")
        box.prop_search(st, "color_image", bpy.data, "images", text="")
        box.prop(st, "color_slot", text="Color")
        box.operator(THEATERRIG_OT_make_color_slot.bl_idname, icon="IMAGE_ALPHA")
        box = lay.box()
        box.label(text="Tile textures", icon="TEXTURE")
        box.operator(THEATERRIG_OT_pick_tile_texture.bl_idname, icon="EYEDROPPER")
        box.prop_search(st, "tile_image", bpy.data, "images", text="")
        row = box.row(align=True)
        row.prop(st, "tile_columns")
        row.prop(st, "tile_rows")
        box.prop(st, "tile_names", text="Names")
        box.prop(st, "tile_default")
        box.operator(THEATERRIG_OT_make_tiles.bl_idname, icon="MESH_GRID")
        arm = an.find_armature(context)
        made = tiles.stored(arm) if arm else {}
        if made:
            shown = ", ".join(sorted(made)[:6]) + (" ..." if len(made) > 6 else "")
            box.label(text=f"{len(made)} tile(s): {shown}")
            box.operator(THEATERRIG_OT_clear_tiles.bl_idname, icon="X")
        lay.separator()
        lay.label(text="Last (removes colliders and VRM data):")
        lay.operator(THEATERRIG_OT_export.bl_idname, icon="EXPORT")


CLASSES = (
    TheaterRigState,
    THEATERRIG_OT_analyse,
    THEATERRIG_OT_detoonify,
    THEATERRIG_OT_rename_mixamo,
    THEATERRIG_OT_rename_springs,
    THEATERRIG_OT_align_bones,
    THEATERRIG_OT_tpose,
    THEATERRIG_OT_pick_texture,
    THEATERRIG_OT_make_color_slot,
    THEATERRIG_OT_pick_tile_texture,
    THEATERRIG_OT_make_tiles,
    THEATERRIG_OT_clear_tiles,
    THEATERRIG_OT_export,
    THEATERRIG_PT_panel,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.theater_rig = bpy.props.PointerProperty(type=TheaterRigState)


def unregister():
    del bpy.types.Scene.theater_rig
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
