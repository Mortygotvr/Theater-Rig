"""Clean-up done by Export: the VRM colliders (the renderer makes its own from
the Mixamo bones) and the VRM add-on's data on the armature, materials,
objects and scene, so the avatar is a plain Blender model. Colliders first:
they're found through the VRM data."""

import bpy

PROP = "vrm_addon_extension"


def _ids():
    for coll in (bpy.data.armatures, bpy.data.materials, bpy.data.objects, bpy.data.meshes, bpy.data.scenes, bpy.data.textures, bpy.data.images):
        yield from coll


def _tree(obj):
    out = [obj]
    for child in obj.children:
        out += _tree(child)
    return out


def collider_objects(arm):
    """Objects the VRM data uses as colliders, plus anything under the armature
    named 'collider' (a plain GLB that kept them)."""
    found = set()
    ext = getattr(arm.data, PROP, None)
    if ext is not None:
        for group in ext.vrm0.secondary_animation.collider_groups:
            for c in group.colliders:
                if c.bpy_object:
                    found.add(c.bpy_object)
        for c in ext.spring_bone1.colliders:
            if getattr(c, "bpy_object", None):
                found.add(c.bpy_object)
    for obj in bpy.data.objects:
        if obj.type != "MESH" and obj.type != "ARMATURE" and "collider" in obj.name.lower():
            parent = obj.parent
            while parent and parent != arm:
                parent = parent.parent
            if parent == arm:
                found.add(obj)
    return found


def remove_colliders(arm):
    """Deletes the collider objects (and what hangs under them). Returns how many."""
    doomed = {o for obj in collider_objects(arm) for o in _tree(obj)}
    for obj in doomed:
        bpy.data.objects.remove(obj, do_unlink=True)
    return len(doomed)


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
