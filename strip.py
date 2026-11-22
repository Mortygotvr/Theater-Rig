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


def _anim_datas(obj):
    """The animation data of an object and of its shape keys."""
    out = [getattr(obj, "animation_data", None)]
    keys = getattr(getattr(obj, "data", None), "shape_keys", None)
    out.append(getattr(keys, "animation_data", None) if keys else None)
    return [ad for ad in out if ad is not None]


def _actions_in(ad):
    out = [ad.action] if ad.action else []
    for track in ad.nla_tracks:
        out += [s.action for s in track.strips if s.action]
    return out


def avatar_animations(arm, keep=None):
    """The avatar's animations (its armature's and its meshes' shape keys':
    active, on NLA tracks, or kept with a fake user and moving its bones),
    but `keep` and any another object uses (an imported Mixamo skeleton's,
    which moves bones of the same names)."""
    from . import anim_export
    from . import export
    objs = export.avatar_objects(arm)
    here, others = set(), set()
    for o in bpy.data.objects:
        for ad in _anim_datas(o):
            (here if o in objs else others).update(_actions_in(ad))
    here |= {a for a in bpy.data.actions if a.use_fake_user and anim_export._moves_bones(a, arm)}
    return sorted((a for a in here - others if a != keep), key=lambda a: a.name)


def remove_animations(arm, keep_default=True):
    """Strips the avatar's animations (avatar_animations): off its armature,
    meshes and NLA tracks, and deleted. Its Default animation stays, unless
    `keep_default` is False. Returns the names removed."""
    from . import export
    keep = export.default_action(arm) if keep_default else None
    gone = avatar_animations(arm, keep)
    if not gone:
        return []
    names = [a.name for a in gone]
    for o in export.avatar_objects(arm):
        for ad in _anim_datas(o):
            if ad.action in gone:
                ad.action = None
            for track in list(ad.nla_tracks):
                for s in list(track.strips):
                    if s.action in gone:
                        track.strips.remove(s)
                if not track.strips:
                    ad.nla_tracks.remove(track)
    for a in gone:
        bpy.data.actions.remove(a)
    if not keep_default and getattr(arm.data, export.DEFAULT_PROP, ""):
        setattr(arm.data, export.DEFAULT_PROP, "")
    return names
