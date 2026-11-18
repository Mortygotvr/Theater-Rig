"""Export: the avatar (armature and the meshes it deforms) as a GLB with the
options the renderer needs. First the tile textures are copied from the VRM
expressions (tiles.py), then the VRM colliders and VRM data go (see
strip.py). Custom properties go in as extras (shade_color, color_default,
spring settings, theater_tiles); shape keys, skin and animations (the
renderer plays them) are kept; modifiers aren't applied (that would drop the
shape keys)."""

import bpy

from . import analyse as an
from . import detoon
from . import strip
from . import tiles


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
    try:
        bpy.ops.export_scene.gltf(
            filepath=filepath,
            export_format="GLB",
            use_selection=True,
            export_extras=True,
            export_apply=False,
            export_skins=True,
            export_morph=True,
            # The avatar's own animations (each action a clip; the renderer plays them)
            export_animations=True,
            export_yup=True,
        )
    finally:
        for o in view_layer.objects:
            o.select_set(o in was_selected)
        view_layer.objects.active = was_active
    return arm, found, colliders, tiled
