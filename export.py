"""Export: the avatar (armature and the meshes it deforms) as a GLB with the
options the renderer needs. First the tile textures are copied from the VRM
expressions (tiles.py), then the VRM colliders and VRM data go (see
strip.py). Custom properties go in as extras (shade_color, color_default,
spring settings, theater_tiles); shape keys and skin are kept; modifiers
aren't applied (that would drop the shape keys). One animation only: the
avatar's default (its armature's "Default animation"), first in the file,
tagged `theater_default`: Theater Puppet loops it, other viewers autoplay it.
The others are their own GLBs (Export Animation), in Puppet's Animation
folder."""

import re

import bpy

from . import analyse as an
from . import detoon
from . import strip
from . import tiles

DEFAULT_PROP = "theater_default_animation"
DEFAULT_EXTRA = "theater_default"


def default_action(arm):
    """The avatar's default animation (its armature's setting), if it's there."""
    name = getattr(arm.data, DEFAULT_PROP, "") if arm else ""
    return bpy.data.actions.get(name) if name else None


def slots_of(act, id_type):
    """The action's slots for `id_type` ("OBJECT": bones, "KEY": shape keys).
    Before Blender 4.4 (no slots): [None] if the action is for that type."""
    if hasattr(act, "slots"):
        return [s for s in act.slots if s.target_id_type == id_type]
    root = getattr(act, "id_root", "OBJECT") or "OBJECT"
    return [None] if root == id_type else []


def keyed_shapes(act, slot):
    """The names of the shape keys the action's `slot` moves."""
    paths = []
    if slot is not None:
        for layer in act.layers:
            for strip in layer.strips:
                bag = strip.channelbag(slot) if hasattr(strip, "channelbag") else None
                if bag is not None:
                    paths += [fc.data_path for fc in bag.fcurves]
    else:
        paths = [fc.data_path for fc in getattr(act, "fcurves", [])]
    return {m.group(1) for m in (re.match(r'key_blocks\["(.+?)"\]', p) for p in paths) if m}


def default_targets(act, arm, objs):
    """Where the Default animation plays: (datablock, slot) pairs. Its bones on
    the armature; its shape keys (a blendshape animation lives on the mesh's
    shape keys, not on the armature) on each avatar mesh having those keys."""
    out = [(arm, s) for s in slots_of(act, "OBJECT")[:1]]
    for slot in slots_of(act, "KEY"):
        names = keyed_shapes(act, slot)
        for o in objs:
            key = getattr(getattr(o, "data", None), "shape_keys", None) if o.type == "MESH" else None
            if key is not None and all(key is not k for k, _ in out) and (not names or any(n in key.key_blocks for n in names)):
                out.append((key, slot))
    return out


def avatar_objects(arm):
    return [arm] + [o for o in bpy.data.objects
                    if o.parent == arm or any(m.type == "ARMATURE" and m.object == arm for m in getattr(o, "modifiers", []))]


def warnings(arm):
    """What the earlier buttons would still change (the export goes ahead)."""
    rep = an.analyse()
    out = []
    if rep.mtoon_materials:
        out.append(f"{len(rep.mtoon_materials)} MToon material(s): run Detoonify")
    if any(r.bone != r.target for r in rep.roles):
        out.append("bones not in Mixamo names: run Rename Bones")
    if rep.springs and any(not s.roots[0].startswith("spring_") for s in rep.springs):
        out.append("spring bones not renamed: run Rename Springs")
    if any(detoon.is_outline_modifier(m) for o in avatar_objects(arm) for m in getattr(o, "modifiers", [])):
        out.append("MToon outlines left: run Detoonify")
    return out


def export_glb(context, filepath):
    """Warns about skipped steps, keeps the tile textures, removes the colliders
    and the VRM data from the scene (Ctrl+Z brings them back), then exports.
    Returns (armature, warnings, colliders removed, expressions with tiles)."""
    arm = an.find_armature(context)
    if arm is None:
        return None, [], 0, 0
    found = warnings(arm)
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    # A tile being tested: back to normal first (or it would be exported)
    tiles.restore(arm)
    # Each spring kind's settings on its every chain (the GLB has them per chain)
    from . import spring_preview
    spring_preview.sync(arm)
    tiled = tiles.store(arm)
    colliders = strip.remove_colliders(arm)
    strip.remove_vrm_data()
    context.view_layer.update()   # drop the deleted objects from the view layer's list
    objs = avatar_objects(arm)
    # Select just the avatar for the export, then put the selection back
    view_layer = context.view_layer
    was_selected = [o for o in view_layer.objects if o.select_get()]
    was_active = view_layer.objects.active
    for o in view_layer.objects:
        o.select_set(o in objs)
    # The default animation alone (no NLA blended in): its bones as the
    # armature's action, its shape keys as the meshes' shape keys' action.
    # Everything else animated stays out (the others' actions off meanwhile)
    act = default_action(arm)
    targets = default_targets(act, arm, objs) if act is not None else []
    if act is not None and not targets:
        found.append(f"Default animation '{act.name}' moves nothing of this avatar: not exported")
        act = None
    held = [arm] + [o.data.shape_keys for o in objs if o.type == "MESH" and getattr(o.data, "shape_keys", None)]
    keep = []
    for idb in held:
        ad = idb.animation_data
        if ad is None and act is None:
            continue
        ad = ad or idb.animation_data_create()
        keep.append((ad, ad.action, getattr(ad, "action_slot", None), ad.use_nla))
        ad.action, ad.use_nla = None, False
    for idb, slot in targets:
        ad = idb.animation_data
        ad.action = act
        if slot is not None:
            ad.action_slot = slot
    from . import contacts
    contacts.export_as = (act.name, act) if act is not None else None
    from . import colour
    previews = colour.neutral_previews().__enter__()
    try:
        bpy.ops.export_scene.gltf(
            filepath=filepath,
            export_format="GLB",
            use_selection=True,
            export_extras=True,
            export_apply=False,
            export_skins=True,
            export_morph=True,
            export_animations=act is not None,
            export_animation_mode="ACTIVE_ACTIONS",
            export_yup=True,
        )
    finally:
        previews.__exit__(None, None, None)
        contacts.export_as = None
        for ad, action, slot, nla in keep:
            ad.action = action
            if slot is not None and action is not None:
                try:
                    ad.action_slot = slot
                except Exception:
                    pass
            ad.use_nla = nla
        for o in view_layer.objects:
            o.select_set(o in was_selected)
        view_layer.objects.active = was_active
    if act is not None:
        from . import anim_export
        anim_export._name_animation(filepath, act.name, {DEFAULT_EXTRA: True})
    return arm, found, colliders, tiled


def export_prop(context, filepath):
    """The selected meshes alone, without the armature (no skin): each where it
    is next to the avatar, its rest shape (armature modifiers off for the
    export), its shape keys and custom properties kept. A prop or a part that
    Theater Puppet draws as an Also draw GLB lines up with the avatar.
    Returns the meshes exported (none: nothing selected)."""
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    view_layer = context.view_layer
    meshes = [o for o in view_layer.objects if o.select_get() and o.type == "MESH"]
    if not meshes:
        return []
    was_selected = [o for o in view_layer.objects if o.select_get()]
    was_active = view_layer.objects.active
    # Their rest shape: the armature's pose doesn't bend them on the way out
    switched = [(m, m.show_viewport, m.show_render) for o in meshes for m in o.modifiers if m.type == "ARMATURE"]
    for m, _, _ in switched:
        m.show_viewport = False
        m.show_render = False
    animated = [o for o in meshes if getattr(o.data, "shape_keys", None) and o.data.shape_keys.animation_data]
    for o in view_layer.objects:
        o.select_set(o in meshes)
    try:
        bpy.ops.export_scene.gltf(
            filepath=filepath,
            export_format="GLB",
            use_selection=True,
            export_extras=True,
            export_apply=False,
            export_skins=False,
            export_morph=True,
            # Their shape keys' animations (a blendshape prop: a tentacle
            # waving), each its own clip named after its action
            export_animations=bool(animated),
            export_animation_mode="ACTIONS",
            export_yup=True,
        )
    finally:
        for m, viewport, render in switched:
            m.show_viewport = viewport
            m.show_render = render
        for o in view_layer.objects:
            o.select_set(o in was_selected)
        view_layer.objects.active = was_active
    return meshes
