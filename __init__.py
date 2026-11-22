"""Theater Rig: prepares VRM and GLB avatars for the Theater avatar renderer by
renaming parts to its convention (see conventions.py)."""

# Already loaded once: this is Reload Scripts (F3), so the other files reload too
_reloading = "bpy" in locals()

import os

import bpy
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import conventions
from . import analyse as an
from . import align
from . import colour
from . import detoon
from . import export
from . import mixamo
from . import anim_export
from . import rename
from . import springs
from . import strip
from . import tiles
from . import tpose
from . import spring_preview
from . import cloth_bones
from . import contacts

# The glTF exporter calls enabled add-ons' hooks: contact frames (contacts.py)
glTF2ExportUserExtension = contacts.glTF2ExportUserExtension

if _reloading:
    import importlib

    # Dependencies first: conventions, then analyse, then what uses them
    # (A preview running is stopped first: its timer calls the old module)
    try:
        spring_preview.stop()
    except Exception:
        pass
    for _module in (conventions, an, rename, detoon, springs, align, tpose, colour, strip, tiles, export, spring_preview, cloth_bones):
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
        if arm is not None:
            # Their settings by kind, from the chains' own (the VRM's)
            spring_preview.ensure_settings(arm)
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


class _MixamoFiles(ImportHelper):
    filename_ext = ".fbx"
    filter_glob: bpy.props.StringProperty(default="*.fbx;*.dae", options={"HIDDEN"})
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    def paths(self):
        return [os.path.join(self.directory, f.name) for f in self.files if f.name] or [self.filepath]


class THEATERRIG_OT_import_mixamo(bpy.types.Operator, _MixamoFiles):
    """Mixamo animations (FBX, or DAE downloaded With Skin) into the scene, each as its own
    skeleton named after the file, next to the avatar (not on it): watch it, change it,
    then Export Animation. Undo with Ctrl+Z"""

    bl_idname = "theater_rig.import_mixamo"
    bl_label = "Import Mixamo"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        done, failed, made = [], [], []
        for path in self.paths():
            try:
                arm, frames, _ = mixamo.import_file(context, path)
                made.append(arm)
                done.append(f"{arm.name} ({frames} frames)")
            except Exception as e:
                failed.append(f"{os.path.basename(path)}: {e}")
        view = context.view_layer
        if made:
            for o in [o for o in view.objects if o is not None]:
                o.select_set(o in made)
            view.objects.active = made[-1]
        if failed:
            self.report({"WARNING"}, "Not imported: " + "; ".join(failed))
        if done:
            self.report({"INFO"}, f"Imported {', '.join(done)}: select it and Export Animation for Puppet")
            return {"FINISHED"}
        return {"CANCELLED"}


class THEATERRIG_OT_convert_mixamo(bpy.types.Operator, _MixamoFiles):
    """Mixamo animations (FBX, or DAE With Skin) straight to animation GLBs for Theater Puppet: one per
    file, next to it, same name (Import Mixamo and Export Animation at once).
    Nothing changes in the scene"""

    bl_idname = "theater_rig.convert_mixamo"
    bl_label = "Convert Mixamo to Animation GLB"
    bl_options = {"REGISTER"}

    def execute(self, context):
        paths = self.paths()
        done, failed = [], []
        for path in paths:
            try:
                out, _ = mixamo.convert(context, path)
                done.append(os.path.basename(out))
            except Exception as e:
                failed.append(f"{os.path.basename(path)}: {e}")
        if failed:
            self.report({"WARNING"}, "Not converted: " + "; ".join(failed))
        if done:
            self.report({"INFO"}, f"Made {', '.join(done)} in {os.path.dirname(paths[0])}: Puppet's Animation folder")
            return {"FINISHED"}
        return {"CANCELLED"}


def _animation_skeletons(context):
    """The selected armatures with Mixamo bone names (else the active object, if it is one)."""
    sel = [o for o in context.selected_objects if anim_export.is_mixamo(o)]
    if not sel and anim_export.is_mixamo(context.active_object):
        sel = [context.active_object]
    return sel


class THEATERRIG_OT_export_animations(bpy.types.Operator):
    """The selected skeletons' animations (any armature with Mixamo bone names, in a
    T-pose: an imported Mixamo one, the avatar's…) as animation GLBs for Theater
    Puppet's Animation folder: each action its own GLB, named after it, with its
    contact frames. Any avatar plays them. (Export GLB has no animation)"""

    bl_idname = "theater_rig.export_animations"
    bl_label = "Export Animation"
    bl_options = {"REGISTER"}

    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def _check(self, context):
        arms = _animation_skeletons(context)
        if not arms:
            return None, "Select a skeleton with Mixamo bone names (Import Mixamo, or Rename to Mixamo)"
        if not any(anim_export.actions_of(a) for a in arms):
            return None, "No animation on the selected skeleton(s): make one in the Dope Sheet"
        for a in arms:
            bent = anim_export.not_t_posed(a)
            if bent:
                return None, f"{a.name} isn't in a T-pose at rest (" + ", ".join(f"{b} {d} deg" for b, d in bent[:3]) + "): Puppet needs one"
        return arms, ""

    def invoke(self, context, event):
        arms, why = self._check(context)
        if arms is None:
            self.report({"ERROR"}, why)
            return {"CANCELLED"}
        if not self.directory:
            base = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
            self.directory = os.path.join(base, "animations") + os.sep
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        arms, why = self._check(context)
        if arms is None:
            self.report({"ERROR"}, why)
            return {"CANCELLED"}
        done = []
        for a in arms:
            done += anim_export.export_actions(context, a, self.directory)
        self.report({"INFO"}, f"Exported {', '.join(n for n, _ in done)} to {self.directory}: Puppet's Animation folder")
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


class _PickTexture:
    """Takes the base colour texture of the selection. In Edit Mode, the selected
    faces' (select a few faces of the part, L on it); in Object Mode, with more
    than one texture on the selected objects, a list to choose from"""

    bl_options = {"REGISTER", "INTERNAL"}
    image: bpy.props.StringProperty(options={"SKIP_SAVE", "HIDDEN"})
    target = ""

    def _set(self, context, img, how):
        setattr(context.scene.theater_rig, self.target, img)
        self.report({"INFO"}, f"{img.name} ({how})")
        return {"FINISHED"}

    def invoke(self, context, event):
        if self.image:
            return self.execute(context)
        found = colour.images_of_selection(context)
        if not found:
            where = "the selected faces" if context.mode == "EDIT_MESH" else "the selected objects"
            self.report({"ERROR"}, f"No base colour texture on {where}")
            return {"CANCELLED"}
        if len(found) == 1 or context.mode == "EDIT_MESH":
            img, names, n = found[0]
            others = f"; also {', '.join(i.name for i, _, _ in found[1:])}: select fewer faces for those" if len(found) > 1 else ""
            how = f"{n} selected face(s), {', '.join(names)}{others}" if n else f"from {', '.join(names)}"
            return self._set(context, img, how)
        idname = self.bl_idname

        def draw(menu, _context):
            col = menu.layout.column()
            col.label(text="Tip: in Edit Mode, select faces of the part, then Pick")
            for img, names, _ in found:
                op = col.operator(idname, text=f"{img.name}  ({', '.join(names)})", icon_value=menu.layout.icon(img))
                op.image = img.name

        context.window_manager.popup_menu(draw, title=f"{len(found)} textures: which one?", icon="TEXTURE")
        return {"FINISHED"}

    def execute(self, context):
        img = bpy.data.images.get(self.image) if self.image else None
        if img is None:
            found = colour.images_of_selection(context)
            if not found:
                self.report({"ERROR"}, "No base colour texture on the selection")
                return {"CANCELLED"}
            img = found[0][0]
        return self._set(context, img, "chosen")


class THEATERRIG_OT_pick_texture(_PickTexture, bpy.types.Operator):
    __doc__ = _PickTexture.__doc__
    bl_idname = "theater_rig.pick_texture"
    bl_label = "Pick from Selected"
    target = "color_image"


class THEATERRIG_OT_pick_tile_texture(_PickTexture, bpy.types.Operator):
    __doc__ = _PickTexture.__doc__
    bl_idname = "theater_rig.pick_tile_texture"
    bl_label = "Pick from Selected"
    target = "tile_image"


class THEATERRIG_OT_make_tiles(bpy.types.Operator):
    """Splits the texture into a grid of named tiles (across then down) on every material
    using it: one set (its name, else the texture's), replacing that set. Undo with Ctrl+Z"""

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
            count, kinds = tiles.make(arm, st.tile_image, st.tile_columns, st.tile_rows, st.tile_names, st.tile_default, st.tile_set)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        moved = [m for m, k in kinds.items() if k == "cell"]
        how = f"{len(moved)} already on one cell (moved)" if moved else ""
        shrunk = [m for m, k in kinds.items() if k == "sheet"]
        if shrunk:
            how += (", " if how else "") + f"{len(shrunk)} over the whole sheet (now showing cell {st.tile_default})"
        group = tiles.set_name_of(st.tile_image, st.tile_set)
        self.report({"INFO"}, f"Set '{group}': {count} tile(s) on {len(kinds)} material(s): {how}")
        return {"FINISHED"}


class THEATERRIG_OT_convert_tiles(bpy.types.Operator):
    """The VRM expressions that move a texture, as named tiles: the set 'expressions'
    (Export does it too, if it hasn't been done). Undo with Ctrl+Z"""

    bl_idname = "theater_rig.convert_tiles"
    bl_label = "Convert VRM Tiles"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm = an.find_armature(context)
        if arm is None:
            self.report({"ERROR"}, "No armature")
            return {"CANCELLED"}
        n = tiles.convert(arm)
        if not n:
            self.report({"WARNING"}, "No VRM expression moves a texture (or no VRM data)")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Set '{tiles.VRM_SET}': {n} tile(s)")
        return {"FINISHED"}


class THEATERRIG_OT_remove_tile_set(bpy.types.Operator):
    """Removes this set's tiles. Undo with Ctrl+Z"""

    bl_idname = "theater_rig.remove_tile_set"
    bl_label = "Remove Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty()

    def execute(self, context):
        arm = an.find_armature(context)
        if arm is None:
            return {"CANCELLED"}
        self.report({"INFO"}, f"Removed {tiles.remove_set(arm, self.set_name)} tile(s)")
        return {"FINISHED"}


def _tile_items(self, context):
    arm = an.find_armature(context)
    items = []
    for group, names in (tiles.sets(arm) if arm else {}).items():
        for n in names:
            items.append((n, n, f"Set {group or '(no set)'}"))
    return items or [("", "(no tiles)", "")]


class THEATERRIG_OT_test_tile(bpy.types.Operator):
    """Shows a tile in Blender, as Theater Puppet shows it (Material Preview or Rendered view).
Back to Normal (and Export) puts the materials back"""

    bl_idname = "theater_rig.test_tile"
    bl_label = "Test Tile"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "tile"

    tile: bpy.props.EnumProperty(name="Tile", items=_tile_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        arm = an.find_armature(context)
        if arm is None or not self.tile:
            return {"CANCELLED"}
        try:
            n = tiles.test(arm, self.tile)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Showing tile '{self.tile}' on {n} material(s)")
        return {"FINISHED"}


class THEATERRIG_OT_step_tile(bpy.types.Operator):
    """Shows the set's next (or previous) tile in Blender, as Theater Puppet's "next" goes through it"""

    bl_idname = "theater_rig.step_tile"
    bl_label = "Next Tile"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty()
    by: bpy.props.IntProperty(default=1)

    def execute(self, context):
        arm = an.find_armature(context)
        if arm is None:
            return {"CANCELLED"}
        try:
            name = tiles.step(arm, self.set_name, self.by)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Showing tile '{name}'")
        return {"FINISHED"}


class THEATERRIG_OT_restore_tiles(bpy.types.Operator):
    """Puts the materials back as they were before Test Tile (Export does it too)"""

    bl_idname = "theater_rig.restore_tiles"
    bl_label = "Back to Normal"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm = an.find_armature(context)
        n = tiles.restore(arm)
        self.report({"INFO"}, f"{n} material(s) back to normal")
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
    options the renderer needs (custom properties, shape keys, skin; its Default animation only).
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


class THEATERRIG_OT_export_prop(bpy.types.Operator, ExportHelper):
    """Exports the selected meshes alone, without the armature (no skin): each where it is
    next to the avatar, in its rest shape, its shape keys kept. For a prop or a part Theater
    Puppet draws with the avatar (Also draw): it lines up. Nothing is removed from the scene"""

    bl_idname = "theater_rig.export_prop"
    bl_label = "Export Prop GLB"
    bl_options = {"REGISTER"}

    filename_ext = ".glb"
    filter_glob: bpy.props.StringProperty(default="*.glb", options={"HIDDEN"})

    def invoke(self, context, event):
        if not any(o.type == "MESH" for o in context.selected_objects):
            self.report({"ERROR"}, "Select the prop's mesh(es) first")
            return {"CANCELLED"}
        obj = context.active_object if context.active_object and context.active_object.type == "MESH" else next(o for o in context.selected_objects if o.type == "MESH")
        folder = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
        self.filepath = os.path.join(folder, obj.name + ".glb")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        meshes = export.export_prop(context, self.filepath)
        if not meshes:
            self.report({"ERROR"}, "Select the prop's mesh(es) first")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Exported {os.path.basename(self.filepath)}: {', '.join(o.name for o in meshes)} (no armature)")
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


class THEATERRIG_OT_delete_unused_springs(bpy.types.Operator):
    """Deletes the spring chains that bend nothing (none of their bones is weighted on the avatar's meshes in the scene): Puppet won't simulate them. Chains' end bones are kept (they set the bone before's length). Undo with Ctrl+Z"""

    bl_idname = "theater_rig.delete_unused_springs"
    bl_label = "Delete Unused Spring Chains"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        arm = an.find_armature(context)
        if arm is None:
            return {"CANCELLED"}
        chains, ends = spring_preview.unused(arm)
        if not chains:
            self.report({"INFO"}, f"No unused spring chain (every chain bends the mesh; {ends} end bone(s) without weight kept: they set the bone before's length)")
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(self, event, title=f"Delete {len(chains)} unused spring chain(s)?", message=", ".join(chains[:8]) + (" …" if len(chains) > 8 else ""))

    def execute(self, context):
        arm = an.find_armature(context)
        if arm is None:
            return {"CANCELLED"}
        if spring_preview.running():
            spring_preview.stop()
        _, ends = spring_preview.unused(arm)
        deleted = spring_preview.delete_unused(arm)
        if not deleted:
            self.report({"INFO"}, "No unused spring chain")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Deleted {len(deleted)} unused chain(s): {', '.join(deleted)} ({ends} end bone(s) without weight kept)")
        return {"FINISHED"}


class THEATERRIG_OT_spring_groups(bpy.types.Operator):
    """One set of settings per kind of spring (hair, bust, skirt…), started from the average of each kind's chains"""

    bl_idname = "theater_rig.spring_groups"
    bl_label = "Group by Kind"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        arm = an.find_armature(context)
        if arm is None or not spring_preview.roots(arm):
            self.report({"ERROR"}, "No spring_<kind>_<n> chains: Rename Springs first")
            return {"CANCELLED"}
        spring_preview.ensure_settings(arm)
        self.report({"INFO"}, f"{len(spring_preview.kinds(arm))} kind(s): " + ", ".join(spring_preview.kinds(arm)))
        return {"FINISHED"}


class THEATERRIG_OT_spring_preview(bpy.types.Operator):
    """Swings the spring chains (spring_<kind>_<n>) as Theater Puppet does: move the
    armature, pose it or play an animation to see them. Click again to stop: every
    bone goes back as it was"""

    bl_idname = "theater_rig.spring_preview"
    bl_label = "Spring Preview"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if spring_preview.running():
            spring_preview.stop()
            self.report({"INFO"}, "Spring preview stopped: the bones are back as they were")
            return {"FINISHED"}
        arm = an.find_armature(context)
        if arm is None:
            self.report({"ERROR"}, "No armature")
            return {"CANCELLED"}
        if not spring_preview.roots(arm):
            self.report({"ERROR"}, "No spring_<kind>_<n> chains: Rename Springs first")
            return {"CANCELLED"}
        p = spring_preview.start(arm)
        self.report({"INFO"}, f"Spring preview: {len(spring_preview.roots(arm))} chain(s), {len(p.joints)} bone(s), {len(p.colliders)} collider(s)")
        return {"FINISHED"}


class THEATERRIG_OT_make_cloth_bones(bpy.types.Operator):
    """Spring chains and their weights for the selected part of the active mesh (its faces in
    Edit Mode), or for the faces of the material picked: a skirt becomes a ring of chains, a
    cape a row of them. Making the same name again replaces it. Undo with Ctrl+Z"""

    bl_idname = "theater_rig.make_cloth_bones"
    bl_label = "Make Cloth Bones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.theater_rig
        arm = an.find_armature(context)
        obj = context.active_object
        if st.cloth_material and (obj is None or obj.type != "MESH" or st.cloth_material.name not in [s.material.name for s in obj.material_slots if s.material]):
            # The mesh that has the material
            obj = next((o for o in bpy.data.objects if o.type == "MESH" and any(s.material == st.cloth_material for s in o.material_slots)), obj)
        if arm is None or obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select the cloth's mesh (and its faces in Edit Mode), or pick its material")
            return {"CANCELLED"}
        try:
            name, shape, chains = cloth_bones.make(arm, obj, st.cloth_columns, st.cloth_rows, st.cloth_kind, st.cloth_parent,
                                                    st.cloth_material.name if st.cloth_material else None, st.cloth_name)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        st.cloth_name = name
        cloth_arm = an.find_armature(context)
        if cloth_arm is not None:
            spring_preview.ensure_settings(cloth_arm)
        self.report({"INFO"}, f"Cloth '{name}': a {shape} of {len(chains)} chain(s) of {st.cloth_rows} bone(s). Try it with Spring Preview")
        return {"FINISHED"}


class THEATERRIG_OT_remove_cloth(bpy.types.Operator):
    """Removes this cloth's bones and weights (the mesh keeps its other weights). Undo with Ctrl+Z"""

    bl_idname = "theater_rig.remove_cloth"
    bl_label = "Remove Cloth"
    bl_options = {"REGISTER", "UNDO"}

    cloth: bpy.props.StringProperty()

    def execute(self, context):
        arm = an.find_armature(context)
        if arm is None or not cloth_bones.remove(arm, self.cloth):
            return {"CANCELLED"}
        self.report({"INFO"}, f"Removed cloth '{self.cloth}'")
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
    tile_set: bpy.props.StringProperty(name="Set", description="The set these tiles make (\"next\" and \"random\" go through a set); empty: the texture's name")
    cloth_columns: bpy.props.IntProperty(name="Chains", default=8, min=2, max=64, description="How many chains: around a skirt, across a cape")
    cloth_rows: bpy.props.IntProperty(name="Bones each", default=4, min=1, max=16, description="Bones down each chain")
    cloth_kind: bpy.props.EnumProperty(name="Kind", items=[(k, k.capitalize(), "") for k in cloth_bones.KINDS], default="skirt")
    cloth_parent: bpy.props.StringProperty(name="Hangs from", description="The body bone it hangs from (empty: the nearest to its top)")
    cloth_material: bpy.props.PointerProperty(type=bpy.types.Material, name="Material", description="Its faces are the part (empty: the faces selected in Edit Mode)")
    cloth_name: bpy.props.StringProperty(name="Name", description="Its name (making the same name again replaces it; empty: a new one)")
    spring_sway: bpy.props.BoolProperty(name="Sway the body", description="Turns the hips back and forth while the preview runs (a test without touching anything)")
    spring_show_colliders: bpy.props.BoolProperty(name="Show colliders", default=True, description="Draws the capsules Theater Puppet pushes the springs out of")
    spring_colliders_thick: bpy.props.FloatProperty(name="Colliders thickness", default=1.0, min=0.0, max=3.0, description="As the Puppet source's colliders setting: a multiplier")
    tile_default: bpy.props.IntProperty(name="Default cell", min=0, description="The cell showing when no tile is on (only for a mesh whose UVs cover the whole sheet)")


class THEATERRIG_PT_panel(bpy.types.Panel):
    bl_label = "Theater Rig"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Theater Rig"

    def draw(self, context):
        lay = self.layout
        lay.operator(THEATERRIG_OT_analyse.bl_idname, icon="VIEWZOOM")
        # Animations for Puppet: no avatar needed (not through it)
        box = lay.box()
        box.label(text="Animations (Puppet's Animation folder)", icon="ACTION")
        box.operator(THEATERRIG_OT_import_mixamo.bl_idname, icon="IMPORT")
        box.operator(THEATERRIG_OT_export_animations.bl_idname, icon="EXPORT")
        box.operator(THEATERRIG_OT_convert_mixamo.bl_idname, icon="FILE_REFRESH")
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
        box.prop(st, "tile_set", text="Set")
        box.prop(st, "tile_default")
        box.operator(THEATERRIG_OT_make_tiles.bl_idname, icon="MESH_GRID")
        box.operator(THEATERRIG_OT_convert_tiles.bl_idname, icon="SHAPEKEY_DATA")
        arm = an.find_armature(context)
        now = tiles.tested(arm)
        for group, names in (tiles.sets(arm) if arm else {}).items():
            row = box.row()
            shown = ", ".join(names[:5]) + (" ..." if len(names) > 5 else "")
            row.label(text=f"{group or '(no set)'}: {shown}", icon="TEXTURE")
            sub = row.row(align=True)
            op = sub.operator(THEATERRIG_OT_step_tile.bl_idname, text="", icon="TRIA_LEFT")
            op.set_name, op.by = group, -1
            op = sub.operator(THEATERRIG_OT_step_tile.bl_idname, text="", icon="TRIA_RIGHT")
            op.set_name, op.by = group, 1
            row.operator(THEATERRIG_OT_remove_tile_set.bl_idname, text="", icon="X").set_name = group
        if arm and tiles.sets(arm):
            row = box.row(align=True)
            row.operator(THEATERRIG_OT_test_tile.bl_idname, icon="HIDE_OFF")
            if now:
                row.operator(THEATERRIG_OT_restore_tiles.bl_idname, icon="LOOP_BACK")
                box.label(text=f"Testing: {now} (Material Preview shows it)", icon="INFO")
        box = lay.box()
        box.label(text="Cloth bones (a skirt, a cape, long hair)", icon="MOD_CLOTH")
        box.label(text="Select its faces in Edit Mode, or pick its material:")
        box.prop_search(st, "cloth_material", bpy.data, "materials", text="")
        row = box.row(align=True)
        row.prop(st, "cloth_columns")
        row.prop(st, "cloth_rows")
        box.prop(st, "cloth_kind")
        if arm:
            box.prop_search(st, "cloth_parent", arm.data, "bones", text="Hangs from")
        box.prop(st, "cloth_name")
        box.operator(THEATERRIG_OT_make_cloth_bones.bl_idname, icon="MOD_CLOTH")
        for cname, cloth in (cloth_bones.cloths(arm) if arm else {}).items():
            row = box.row()
            row.label(text=f"{cname}: {cloth['shape']}, {len(cloth['chains'])} × {cloth['rows']} on {cloth['mesh']}")
            row.operator(THEATERRIG_OT_remove_cloth.bl_idname, text="", icon="X").cloth = cname
        box = lay.box()
        box.label(text="Spring preview (as Theater Puppet swings them)", icon="FORCE_WIND")
        on = spring_preview.running()
        box.operator(THEATERRIG_OT_spring_preview.bl_idname, text="Stop Spring Preview" if on else "Start Spring Preview", icon="PAUSE" if on else "PLAY", depress=on)
        box.prop(st, "spring_sway")
        row = box.row(align=True)
        row.prop(st, "spring_show_colliders")
        row.prop(st, "spring_colliders_thick", text="Thickness")
        groups = spring_preview.kinds(arm) if arm else {}
        if not groups:
            box.label(text="No spring chains yet: Rename Springs (or Make Cloth Bones) first.")
        elif not spring_preview.grouped(arm):
            box.label(text="Settings by kind (one for all the hair, one for the bust…):")
            box.operator(THEATERRIG_OT_spring_groups.bl_idname, icon="GROUP_BONE")
        else:
            box.label(text="By kind (Export writes them on every chain of the kind):")
            for kind, bones in groups.items():
                sub = box.box()
                sub.label(text=f"{kind.capitalize()}: {len(bones)} chain(s)", icon="BONE_DATA")
                grid = sub.grid_flow(columns=2, align=True)
                for k in spring_preview.DEFAULTS:
                    grid.prop(arm.data, f'["{spring_preview.kind_key(kind, k)}"]', text=k.capitalize())
        if groups:
            box.operator(THEATERRIG_OT_delete_unused_springs.bl_idname, icon="TRASH")
        lay.separator()
        # The avatar's own animation: in its GLB, looped by Puppet, autoplayed elsewhere
        av = an.find_armature(context)
        if av is not None:
            lay.prop_search(av.data, export.DEFAULT_PROP, bpy.data, "actions", text="Default animation", icon="ACTION")
        lay.label(text="Last (removes colliders and VRM data):")
        lay.operator(THEATERRIG_OT_export.bl_idname, icon="EXPORT")
        lay.label(text="A prop or part, lined up with it (selected meshes, no armature):")
        lay.operator(THEATERRIG_OT_export_prop.bl_idname, icon="EXPORT")


CLASSES = (
    TheaterRigState,
    THEATERRIG_OT_analyse,
    THEATERRIG_OT_detoonify,
    THEATERRIG_OT_rename_mixamo,
    THEATERRIG_OT_rename_springs,
    THEATERRIG_OT_align_bones,
    THEATERRIG_OT_tpose,
    THEATERRIG_OT_import_mixamo,
    THEATERRIG_OT_convert_mixamo,
    THEATERRIG_OT_export_animations,
    THEATERRIG_OT_pick_texture,
    THEATERRIG_OT_make_color_slot,
    THEATERRIG_OT_pick_tile_texture,
    THEATERRIG_OT_make_tiles,
    THEATERRIG_OT_convert_tiles,
    THEATERRIG_OT_remove_tile_set,
    THEATERRIG_OT_test_tile,
    THEATERRIG_OT_step_tile,
    THEATERRIG_OT_restore_tiles,
    THEATERRIG_OT_spring_groups,
    THEATERRIG_OT_delete_unused_springs,
    THEATERRIG_OT_spring_preview,
    THEATERRIG_OT_make_cloth_bones,
    THEATERRIG_OT_remove_cloth,
    THEATERRIG_OT_export,
    THEATERRIG_OT_export_prop,
    THEATERRIG_PT_panel,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.theater_rig = bpy.props.PointerProperty(type=TheaterRigState)
    setattr(bpy.types.Armature, export.DEFAULT_PROP, bpy.props.StringProperty(
        name="Default animation",
        description="The avatar's own animation (breathing, a tail, ears…): in its GLB, first, tagged as its default. "
                    "Theater Puppet loops it, other viewers autoplay it. Every other animation: Export Animation"))
    if spring_preview._on_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(spring_preview._on_load)


def unregister():
    spring_preview.stop()
    if spring_preview._on_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(spring_preview._on_load)
    del bpy.types.Scene.theater_rig
    delattr(bpy.types.Armature, export.DEFAULT_PROP)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
