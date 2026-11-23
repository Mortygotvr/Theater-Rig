"""Theater Rig: prepares VRM and GLB avatars for the Theater avatar renderer by
renaming parts to its convention (see conventions.py)."""

# Already loaded once: this is Reload Scripts (F3), so the other files reload too
_reloading = "bpy" in locals()

import os
import sys

import bpy
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import conventions
from . import analyse as an
from . import align
from . import colour
from . import detoon
from . import export
from . import mixamo
from . import overlay
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
    _order = (conventions, an, rename, detoon, springs, align, tpose, contacts, colour, overlay, strip, tiles, anim_export, mixamo, export, spring_preview, cloth_bones)
    for _module in _order:
        importlib.reload(_module)
    # Every other file of it loaded (palette.py, dae.py…: imported where
    # they're used), so none stays old (a new file forgotten in the list above
    # left overlay.py old: Make Colour Slot failed)
    _done = {m.__name__ for m in _order}
    for _name in sorted(n for n in list(sys.modules) if n.startswith(__name__ + ".") and n not in _done):
        importlib.reload(sys.modules[_name])
    # Those that imported them take the new ones
    for _module in (colour, overlay, mixamo, anim_export):
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


class THEATERRIG_OT_remove_animations(bpy.types.Operator):
    """Strips every animation from the avatar: its armature's and its meshes' shape keys'
    (active, on NLA tracks, kept with a fake user), deleted. Its Default animation stays
    unless unticked. Other skeletons' (an imported Mixamo one) are left. Undo with Ctrl+Z"""

    bl_idname = "theater_rig.remove_animations"
    bl_label = "Remove Animations"
    bl_options = {"REGISTER", "UNDO"}

    keep_default: bpy.props.BoolProperty(name="Keep the Default animation", default=True)

    def invoke(self, context, event):
        arm = an.find_armature(context)
        if arm is None:
            self.report({"ERROR"}, "No armature")
            return {"CANCELLED"}
        keep = export.default_action(arm) if self.keep_default else None
        found = strip.avatar_animations(arm, keep)
        if not found:
            self.report({"INFO"}, "The avatar has no animation" + (f" (but its Default, {keep.name})" if keep else ""))
            return {"CANCELLED"}
        names = ", ".join(a.name for a in found[:8]) + (" …" if len(found) > 8 else "")
        return context.window_manager.invoke_confirm(self, event, title=f"Remove {len(found)} animation(s) from the avatar?", message=names)

    def execute(self, context):
        arm = an.find_armature(context)
        if arm is None:
            self.report({"ERROR"}, "No armature")
            return {"CANCELLED"}
        gone = strip.remove_animations(arm, self.keep_default)
        if not gone:
            self.report({"INFO"}, "The avatar has no animation")
            return {"CANCELLED"}
        kept = export.default_action(arm)
        self.report({"INFO"}, f"Removed {', '.join(gone)}" + (f" (kept the Default, {kept.name})" if kept else ""))
        return {"FINISHED"}


class THEATERRIG_OT_pick_overlay_material(bpy.types.Operator):
    """Takes the material of the selection: in Edit Mode the selected faces', else the active one"""

    bl_idname = "theater_rig.pick_overlay_material"
    bl_label = "Pick from Selected"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        mat = colour.material_of_selection(context)
        if mat is None:
            self.report({"ERROR"}, "No material on the selection")
            return {"CANCELLED"}
        if overlay.PROP in mat:
            self.report({"ERROR"}, f"{mat.name} is an overlay: pick the material under it")
            return {"CANCELLED"}
        context.scene.theater_rig.overlay_material = mat
        self.report({"INFO"}, mat.name)
        return {"FINISHED"}


class THEATERRIG_OT_add_overlay(bpy.types.Operator, ImportHelper):
    """A picture over the material's texture (a logo, a tattoo, a design): a PNG painted on the same
    UV layout, transparent where there's nothing. It keeps its own colours (for a part that changes
    colour: Make Colour Slot, its colours ticked). Undo with Ctrl+Z"""

    bl_idname = "theater_rig.add_overlay"
    bl_label = "Add Overlay…"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".png"
    filter_glob: bpy.props.StringProperty(default="*.png;*.webp;*.tga", options={"HIDDEN"})

    def invoke(self, context, event):
        base = context.scene.theater_rig.overlay_material
        if base is None:
            self.report({"ERROR"}, "Choose the material it lies on first (Pick from Selected)")
            return {"CANCELLED"}
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        base = context.scene.theater_rig.overlay_material
        if base is None:
            self.report({"ERROR"}, "Choose the material it lies on first")
            return {"CANCELLED"}
        try:
            image = bpy.data.images.load(self.filepath, check_existing=True)
            image.alpha_mode = "STRAIGHT"
            image.pack()
            mat, faces = overlay.add(base, image)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{mat.name}: {faces} face(s) over {base.name}")
        return {"FINISHED"}


class THEATERRIG_OT_remove_overlay(bpy.types.Operator):
    """Takes the overlay off: its faces and its material (the material under it is untouched). Undo with Ctrl+Z"""

    bl_idname = "theater_rig.remove_overlay"
    bl_label = "Remove Overlay"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    material: bpy.props.StringProperty()

    def execute(self, context):
        mat = bpy.data.materials.get(self.material)
        if mat is None:
            return {"CANCELLED"}
        faces = overlay.remove(mat)
        self.report({"INFO"}, f"Removed {self.material} ({faces} face(s))")
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


class THEATERRIG_OT_remove_color_slot(bpy.types.Operator):
    """Puts the chosen colour slot's texture back as it was: its materials on their own texture
    again (colours and all), Color<N> out of their names. Undo with Ctrl+Z"""

    bl_idname = "theater_rig.remove_color_slot"
    bl_label = "Remove Colour Slot"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.theater_rig
        grey = st.color_image
        if grey is None or not conventions.color_slot(grey.name) and colour.FROM_PROP not in grey:
            self.report({"ERROR"}, "Choose a colour slot's texture (…_Color<N>) first")
            return {"CANCELLED"}
        try:
            original, mats = colour.remove_color_slot(grey)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        st.color_image = original
        self.report({"INFO"}, f"{original.name} back on {len(mats)} material(s)")
        bpy.ops.theater_rig.analyse()
        return {"FINISHED"}


def colour_users(image):
    """The materials whose base colour is `image`."""
    return [m for m in bpy.data.materials if colour.base_image(m) == image]


class THEATERRIG_OT_make_color_slot(bpy.types.Operator):
    """The texture's ticked colours follow colour slot N (in Blender too: a Multiply node with the
    slot's colour, which you can change to try one); the unticked ones stay as painted. All
    ticked: the whole texture. Undo with Ctrl+Z, or Remove"""

    bl_idname = "theater_rig.make_color_slot"
    bl_label = "Make Colour Slot"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        st = context.scene.theater_rig
        if st.color_image is not None:
            # A texture with an overlay over it: its slot recolours what's UNDER the overlay
            under = [m for m in colour_users(st.color_image) if overlay.over(m)]
            if under:
                tops = ", ".join(o.name for m in under for o in overlay.over(m))
                return context.window_manager.invoke_confirm(
                    self, event, title="This texture has an overlay over it",
                    message=f"Its colour slot recolours everything UNDER the overlay ({tops}), and the overlay keeps its own colours. For the overlay's part to change colour, make the slot on the overlay's texture instead. Recolour the texture under it?",
                    confirm_text="Recolour under it")
        return self.execute(context)

    def execute(self, context):
        st = context.scene.theater_rig
        if st.color_image is None:
            self.report({"ERROR"}, "Choose a texture first")
            return {"CANCELLED"}
        import json
        fams = [(tuple(it.color), it.share, [tuple(m) for m in json.loads(it.members or "[]")] or [tuple(it.color)]) for it in st.palette]
        picked = [it.change for it in st.palette]
        if fams and not any(picked):
            self.report({"ERROR"}, "Tick at least one colour that changes")
            return {"CANCELLED"}
        try:
            if fams and not all(picked):
                # Only those colours: the rest of the texture kept as painted
                grey, mats = colour.make_color_part(st.color_image, st.color_slot, fams, picked)
            else:
                grey, mats = colour.make_color_slot(st.color_image, st.color_slot)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
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
    """Exports the selected meshes, each where it is next to the avatar, its shape keys and
    their animations kept. Bound to an armature: with it and its skin, so in Theater Puppet it
    follows the avatar. For a prop (redeem) or a part (Also draw): it lines up. Nothing is
    removed from the scene"""

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
        bound = sorted({m.object.name for o in meshes for m in o.modifiers if m.type == "ARMATURE" and m.object})
        how = f"with {', '.join(bound)} (follows the avatar)" if bound else "no armature"
        self.report({"INFO"}, f"Exported {os.path.basename(self.filepath)}: {', '.join(o.name for o in meshes)}, {how}")
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


class TheaterRigColour(bpy.types.PropertyGroup):
    """One of the texture's colours (a family: her red and its shades)"""
    color: bpy.props.FloatVectorProperty(subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0)
    share: bpy.props.FloatProperty()
    change: bpy.props.BoolProperty(name="Changes", default=True, description="Follows the colour slot (unticked: kept as painted)")
    members: bpy.props.StringProperty()


def _colours_of_texture(state, context):
    """The chosen texture's colours, as swatches (all ticked: the whole texture)"""
    import json
    from . import palette
    state.palette.clear()
    img = state.color_image
    if img is None or conventions.color_slot(img.name) is not None or img.size[0] == 0:
        return
    try:
        fams = palette.colours(colour.image_rgba(img))
    except Exception:
        return
    for rgb, share, members in fams:
        it = state.palette.add()
        it.color = rgb
        it.share = share
        it.members = json.dumps([list(m) for m in members])


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
    color_image: bpy.props.PointerProperty(type=bpy.types.Image, name="Texture", update=_colours_of_texture)
    palette: bpy.props.CollectionProperty(type=TheaterRigColour)
    overlay_material: bpy.props.PointerProperty(type=bpy.types.Material, name="Material", description="The material the overlay lies on (its texture's UV layout)")

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
        st = context.scene.theater_rig
        arm = an.find_armature(context)

        def section(key, title, icon, closed=True):
            """A section that folds (Blender keeps it open or closed): its body, or None when closed"""
            header, body = lay.panel(f"theater_rig_{key}", default_closed=closed)
            header.label(text=title, icon=icon)
            return body

        if not st.analysed:
            lay.label(text="Select the avatar, then Analyse.")
        else:
            warn = lambda bad: "ERROR" if bad else "CHECKMARK"
            problems = st.missing_roles or st.arkit_missing or st.mtoon or st.outlines
            body = section("report", f"Report: {st.armature}", "ERROR" if problems else "CHECKMARK")
            if body:
                col = body.column(align=True)
                col.label(text=f"{st.armature} ({st.vrm})", icon="ARMATURE_DATA")
                col.label(text=f"Bone roles: {st.roles}, missing {st.missing_roles}", icon=warn(st.missing_roles))
                col.label(text=f"Spring chains: {st.springs}, collider groups: {st.colliders}", icon="FORCE_WIND")
                col.label(text=f"ARKit: {st.arkit_ok} ready, {st.arkit_approx} approximate", icon="SHAPEKEY_DATA")
                col.label(text=f"ARKit missing: {st.arkit_missing} of 52", icon=warn(st.arkit_missing))
                col.label(text=f"MToon materials: {st.mtoon}, outlines: {st.outlines}", icon="MATERIAL")
                col.label(text=f"Colour slots: {st.color_slots}", icon="COLOR")
                body.label(text=f"Details: Text editor > '{REPORT_TEXT}'")

            body = section("prepare", "Prepare (in this order)", "TOOL_SETTINGS", closed=False)
            if body:
                col = body.column(align=True)
                col.operator(THEATERRIG_OT_detoonify.bl_idname, icon="SHADING_SOLID")
                col.operator(THEATERRIG_OT_rename_mixamo.bl_idname, icon="BONE_DATA")
                col.operator(THEATERRIG_OT_rename_springs.bl_idname, icon="FORCE_WIND")
                col.operator(THEATERRIG_OT_align_bones.bl_idname, icon="ORIENTATION_GIMBAL")
                col.operator(THEATERRIG_OT_tpose.bl_idname, icon="ARMATURE_DATA")

            body = section("colour", f"Colour slots ({st.color_slots})", "COLOR")
            if body:
                body.operator(THEATERRIG_OT_pick_texture.bl_idname, icon="EYEDROPPER")
                body.prop_search(st, "color_image", bpy.data, "images", text="")
                if st.palette:
                    col = body.column(align=True)
                    col.label(text="Its colours (ticked: changes; unticked: kept as painted)")
                    for it in st.palette:
                        r = col.row(align=True)
                        r.prop(it, "change", text="")
                        r.prop(it, "color", text="")
                        r.label(text=f"{it.share * 100:.1f}%")
                body.prop(st, "color_slot", text="Color")
                row = body.row(align=True)
                row.operator(THEATERRIG_OT_make_color_slot.bl_idname, icon="IMAGE_ALPHA")
                row.operator(THEATERRIG_OT_remove_color_slot.bl_idname, text="Remove", icon="LOOP_BACK")

            shown = [(m, u) for m, u in overlay.overlays() if colour.PART_PROP not in m]
            body = section("overlay", f"Overlays ({len(shown)})", "IMAGE_RGB_ALPHA")
            if body:
                body.label(text="A picture that keeps its colours (a logo, a design)")
                body.operator(THEATERRIG_OT_pick_overlay_material.bl_idname, icon="EYEDROPPER")
                body.prop_search(st, "overlay_material", bpy.data, "materials", text="")
                body.operator(THEATERRIG_OT_add_overlay.bl_idname, icon="ADD")
                for mat, under in shown:
                    row = body.row()
                    row.label(text=f"{mat.name}", icon="IMAGE_RGB_ALPHA")
                    row.operator(THEATERRIG_OT_remove_overlay.bl_idname, text="", icon="X").material = mat.name

            sets = tiles.sets(arm) if arm else {}
            now = tiles.tested(arm)
            body = section("tiles", f"Tile textures ({len(sets)} set{'s' if len(sets) != 1 else ''})" + (f", testing {now}" if now else ""), "TEXTURE")
            if body:
                body.operator(THEATERRIG_OT_pick_tile_texture.bl_idname, icon="EYEDROPPER")
                body.prop_search(st, "tile_image", bpy.data, "images", text="")
                row = body.row(align=True)
                row.prop(st, "tile_columns")
                row.prop(st, "tile_rows")
                body.prop(st, "tile_names", text="Names")
                body.prop(st, "tile_set", text="Set")
                body.prop(st, "tile_default")
                body.operator(THEATERRIG_OT_make_tiles.bl_idname, icon="MESH_GRID")
                body.operator(THEATERRIG_OT_convert_tiles.bl_idname, icon="SHAPEKEY_DATA")
                for group, names in sets.items():
                    row = body.row()
                    shown_names = ", ".join(names[:5]) + (" ..." if len(names) > 5 else "")
                    row.label(text=f"{group or '(no set)'}: {shown_names}", icon="TEXTURE")
                    sub = row.row(align=True)
                    op = sub.operator(THEATERRIG_OT_step_tile.bl_idname, text="", icon="TRIA_LEFT")
                    op.set_name, op.by = group, -1
                    op = sub.operator(THEATERRIG_OT_step_tile.bl_idname, text="", icon="TRIA_RIGHT")
                    op.set_name, op.by = group, 1
                    row.operator(THEATERRIG_OT_remove_tile_set.bl_idname, text="", icon="X").set_name = group
                if sets:
                    row = body.row(align=True)
                    row.operator(THEATERRIG_OT_test_tile.bl_idname, icon="HIDE_OFF")
                    if now:
                        row.operator(THEATERRIG_OT_restore_tiles.bl_idname, icon="LOOP_BACK")
                        body.label(text=f"Testing: {now} (Material Preview shows it)", icon="INFO")

            cloths = cloth_bones.cloths(arm) if arm else {}
            body = section("cloth", f"Cloth bones ({len(cloths)})", "MOD_CLOTH")
            if body:
                body.label(text="A skirt, a cape, long hair: select its faces in Edit Mode, or pick its material:")
                body.prop_search(st, "cloth_material", bpy.data, "materials", text="")
                row = body.row(align=True)
                row.prop(st, "cloth_columns")
                row.prop(st, "cloth_rows")
                body.prop(st, "cloth_kind")
                if arm:
                    body.prop_search(st, "cloth_parent", arm.data, "bones", text="Hangs from")
                body.prop(st, "cloth_name")
                body.operator(THEATERRIG_OT_make_cloth_bones.bl_idname, icon="MOD_CLOTH")
                for cname, cloth in cloths.items():
                    row = body.row()
                    row.label(text=f"{cname}: {cloth['shape']}, {len(cloth['chains'])} × {cloth['rows']} on {cloth['mesh']}")
                    row.operator(THEATERRIG_OT_remove_cloth.bl_idname, text="", icon="X").cloth = cname

            on = spring_preview.running()
            groups = spring_preview.kinds(arm) if arm else {}
            body = section("springs", f"Spring bones ({len(groups)} kind{'s' if len(groups) != 1 else ''})" + (": previewing" if on else ""), "FORCE_WIND")
            if body:
                body.operator(THEATERRIG_OT_spring_preview.bl_idname, text="Stop Spring Preview" if on else "Start Spring Preview", icon="PAUSE" if on else "PLAY", depress=on)
                body.prop(st, "spring_sway")
                row = body.row(align=True)
                row.prop(st, "spring_show_colliders")
                row.prop(st, "spring_colliders_thick", text="Thickness")
                if not groups:
                    body.label(text="No spring chains yet: Rename Springs (or Make Cloth Bones) first.")
                elif not spring_preview.grouped(arm):
                    body.label(text="Settings by kind (one for all the hair, one for the bust…):")
                    body.operator(THEATERRIG_OT_spring_groups.bl_idname, icon="GROUP_BONE")
                else:
                    body.label(text="By kind (Export writes them on every chain of the kind):")
                    for kind, bones in groups.items():
                        sub = body.box()
                        sub.label(text=f"{kind.capitalize()}: {len(bones)} chain(s)", icon="BONE_DATA")
                        grid = sub.grid_flow(columns=2, align=True)
                        for k in spring_preview.DEFAULTS:
                            grid.prop(arm.data, f'["{spring_preview.kind_key(kind, k)}"]', text=k.capitalize())
                if groups:
                    body.operator(THEATERRIG_OT_delete_unused_springs.bl_idname, icon="TRASH")

        # Animations for Puppet: no avatar needed (not through it)
        body = section("animations", "Animations (Puppet's Animation folder)", "ACTION")
        if body:
            body.operator(THEATERRIG_OT_import_mixamo.bl_idname, icon="IMPORT")
            body.operator(THEATERRIG_OT_export_animations.bl_idname, icon="EXPORT")
            body.operator(THEATERRIG_OT_convert_mixamo.bl_idname, icon="FILE_REFRESH")

        if st.analysed:
            body = section("export", "Export", "EXPORT", closed=False)
            if body:
                # The avatar's own animation: in its GLB, looped by Puppet, autoplayed elsewhere
                if arm is not None:
                    body.prop_search(arm.data, export.DEFAULT_PROP, bpy.data, "actions", text="Default animation", icon="ACTION")
                    body.operator(THEATERRIG_OT_remove_animations.bl_idname, icon="TRASH")
                body.label(text="Last (removes colliders and VRM data):")
                body.operator(THEATERRIG_OT_export.bl_idname, icon="EXPORT")
                body.label(text="A prop or part, lined up with it (selected meshes; bound: follows):")
                body.operator(THEATERRIG_OT_export_prop.bl_idname, icon="EXPORT")

CLASSES = (
    TheaterRigColour,
    TheaterRigState,
    THEATERRIG_OT_analyse,
    THEATERRIG_OT_detoonify,
    THEATERRIG_OT_rename_mixamo,
    THEATERRIG_OT_rename_springs,
    THEATERRIG_OT_align_bones,
    THEATERRIG_OT_tpose,
    THEATERRIG_OT_import_mixamo,
    THEATERRIG_OT_convert_mixamo,
    THEATERRIG_OT_remove_color_slot,
    THEATERRIG_OT_pick_overlay_material,
    THEATERRIG_OT_add_overlay,
    THEATERRIG_OT_remove_overlay,
    THEATERRIG_OT_export_animations,
    THEATERRIG_OT_remove_animations,
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
    tiles.register_handlers()


def unregister():
    tiles.unregister_handlers()
    spring_preview.stop()
    if spring_preview._on_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(spring_preview._on_load)
    del bpy.types.Scene.theater_rig
    delattr(bpy.types.Armature, export.DEFAULT_PROP)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
