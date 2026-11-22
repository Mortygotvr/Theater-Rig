"""Mixamo animations. Import Mixamo: each file (Mixamo's "FBX Binary", with or
without skin) as its own skeleton in the scene, next to the avatar, not on
it: Mixamo's T-pose, bones named without "mixamorig:", its animation as an
action named after the file, to watch or change. Export Animation
(anim_export.py) then writes it for Theater Puppet. Convert: both at once, the
GLB next to the file, nothing left in the scene."""

import os
import re

import bpy

from . import anim_export

PREFIX = re.compile(r"^mixamorig\d*:", re.I)
KINDS = ("objects", "armatures", "meshes", "materials", "actions", "images", "textures")


def plain(name):
    return PREFIX.sub("", name)


def _read(context, path):
    """The file's objects in the scene; returns {kind: datablocks added}."""
    before = {k: set(getattr(bpy.data, k)) for k in KINDS}
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        raise RuntimeError(f"{os.path.basename(path)}: not an FBX")
    return {k: set(getattr(bpy.data, k)) - v for k, v in before.items()}


def _remove(added):
    for o in added["objects"]:
        if o.name in bpy.data.objects and bpy.data.objects[o.name] == o:
            bpy.data.objects.remove(o, do_unlink=True)
    for d in added["actions"]:
        if d.name in bpy.data.actions and bpy.data.actions[d.name] == d:
            bpy.data.actions.remove(d)
    for k in ("armatures", "meshes", "materials", "textures", "images"):
        coll = getattr(bpy.data, k)
        for d in added[k]:
            if d.name in coll and coll[d.name] == d and d.users == 0:
                coll.remove(d)


def import_file(context, path, keep_meshes=True):
    """One Mixamo file as its own skeleton. Returns (armature, frames, {kind: added})."""
    name = os.path.splitext(os.path.basename(path))[0]
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    added = _read(context, path)
    try:
        arm = next((o for o in added["objects"] if o.type == "ARMATURE"), None)
        if arm is None or not (arm.animation_data and arm.animation_data.action):
            raise RuntimeError(f"{os.path.basename(path)}: no animated armature in it")
        for b in arm.data.bones:
            b.name = plain(b.name)
        if not anim_export.is_mixamo(arm):
            raise RuntimeError(f"{os.path.basename(path)}: not a Mixamo skeleton (no Hips, Spine, LeftArm…)")
        act = arm.animation_data.action
        # An earlier import of that name: replaced (its skeleton and meshes too)
        old = bpy.data.actions.get(name)
        if old is not None and old != act:
            for o in list(bpy.data.objects):
                if o.type == "ARMATURE" and o not in added["objects"] and o.animation_data and o.animation_data.action == old:
                    for c in list(o.children_recursive) + [o]:
                        bpy.data.objects.remove(c, do_unlink=True)
            bpy.data.actions.remove(old)
        act.name = name
        act.use_fake_user = True
        arm.name = name
        if not keep_meshes:
            for o in [o for o in added["objects"] if o.type != "ARMATURE"]:
                added["objects"].discard(o)
                bpy.data.objects.remove(o, do_unlink=True)
        f0, f1 = (int(round(x)) for x in act.frame_range)
        return arm, f1 - f0 + 1, added
    except Exception:
        _remove(added)
        raise


def convert(context, path):
    """A Mixamo file as an animation GLB next to it, same name; nothing left
    in the scene. Returns (the GLB's path, frames)."""
    view = context.view_layer
    active = view.objects.active
    selected = [o for o in view.objects if o.select_get()]
    # The FBX import sets the scene to the file's frame rate and range: put back
    scene = context.scene
    timing = (scene.render.fps, scene.render.fps_base, scene.frame_start, scene.frame_end, scene.frame_current)
    added = None
    try:
        arm, frames, added = import_file(context, path, keep_meshes=False)
        done = anim_export.export_actions(context, arm, os.path.dirname(path) or ".", [arm.animation_data.action])
        return done[0][1], frames
    finally:
        if added is not None:
            _remove(added)
        scene.render.fps, scene.render.fps_base, scene.frame_start, scene.frame_end = timing[:4]
        scene.frame_set(timing[4])
        # (Objects just removed can still show there as None)
        for o in [o for o in view.objects if o is not None]:
            o.select_set(o in selected)
        view.objects.active = active
