"""Remove VRM Data: clears what the VRM add-on keeps on the armature, the
materials, the objects and the scene, so the avatar is a plain Blender model
and can't be exported as a VRM by mistake. Run it last: Rename Springs reads
the VRM spring data first."""

import bpy

PROP = "vrm_addon_extension"


def _ids():
    for coll in (bpy.data.armatures, bpy.data.materials, bpy.data.objects, bpy.data.meshes, bpy.data.scenes, bpy.data.textures, bpy.data.images):
        yield from coll


def remove_vrm_data():
    """Returns how many datablocks had VRM data."""
    cleared = 0
    for id_ in _ids():
        if PROP in id_.keys():
            del id_[PROP]
            cleared += 1
        elif hasattr(id_, PROP) and id_.is_property_set(PROP):
            id_.property_unset(PROP)
            cleared += 1
    return cleared
