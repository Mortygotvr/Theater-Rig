"""Export: the avatar (armature and the meshes it deforms) as a GLB with the
options the renderer needs. Custom properties go in as extras (shade_color,
spring settings); shape keys and skin are kept; modifiers aren't applied
(that would drop the shape keys)."""

import bpy

from . import analyse as an
from . import detoon


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
    arm = an.find_armature(context)
    if arm is None:
        return None, []
    found = warnings(arm)
    objs = avatar_objects(arm)
    # Select just the avatar for the export, then put the selection back
    view_layer = context.view_layer
    was_selected = [o for o in view_layer.objects if o.select_get()]
    was_active = view_layer.objects.active
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
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
            export_animations=False,
            export_yup=True,
        )
    finally:
        for o in view_layer.objects:
            o.select_set(o in was_selected)
        view_layer.objects.active = was_active
    return arm, found
