"""Rename: body bones to their Mixamo names, from the roles Analyse found.

Blender renames the matching vertex groups, constraint targets and animation
paths with the bone. The VRM add-on keeps its own bone names (humanoid and
spring data); those are updated here too, so the avatar stays a working VRM."""

import bpy

from . import analyse as an


def _vrm_bone_refs(arm):
    """Every VRM add-on property that names a bone of this armature."""
    ext = getattr(arm.data, "vrm_addon_extension", None)
    if ext is None:
        return []
    refs = []

    def walk(group, depth=0):
        if group is None or depth > 8:
            return
        for prop in group.bl_rna.properties:
            pid = prop.identifier
            if pid in ("rna_type",):
                continue
            if prop.type == "STRING" and pid == "bone_name":
                refs.append(group)
            elif prop.type == "POINTER":
                walk(getattr(group, pid, None), depth + 1)
            elif prop.type == "COLLECTION":
                for item in getattr(group, pid, []):
                    walk(item, depth + 1)

    walk(ext)
    return refs


def rename_bones(arm, roles):
    """Renames each role's bone to its Mixamo name. A bone that already holds a
    target name without being that role is moved aside (suffix _orig).
    Returns [(old, new)]."""
    return rename_bones_map(arm, [(r.bone, r.target) for r in roles])


def rename_bones_map(arm, pairs):
    """Renames bones by [(old, new)]. A bone already holding a target name
    without being renamed itself is moved aside (suffix _orig). VRM add-on
    references follow. Returns [(old, new)] actually done."""
    bones = arm.data.bones
    plan = [(old, new) for old, new in pairs if old != new and old in bones]
    if not plan:
        return []
    refs = _vrm_bone_refs(arm)
    targets = {new for _, new in plan}
    sources = {old for old, _ in plan}

    renamed = {}
    # Bones squatting on a target name, that aren't being renamed themselves
    for name in targets:
        if name in bones and name not in sources:
            aside = name + "_orig"
            bones[name].name = aside
            renamed[name] = bones[aside].name
    # Two passes through temporary names, so swaps and chains can't collide
    temp = {}
    for i, (old, _) in enumerate(plan):
        bones[old].name = f"__theater_rig_tmp_{i}"
        temp[old] = bones[f"__theater_rig_tmp_{i}"].name
    done = []
    for i, (old, new) in enumerate(plan):
        bones[temp[old]].name = new
        renamed[old] = new
        done.append((old, new))

    for ref in refs:
        if ref.bone_name in renamed:
            ref.bone_name = renamed[ref.bone_name]
    return done


def rename_to_mixamo(context=None):
    arm = an.find_armature(context)
    if arm is None:
        return None, []
    rep = an.analyse(context)
    return arm, rename_bones(arm, rep.roles)
