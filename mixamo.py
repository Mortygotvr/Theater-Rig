"""Mixamo animations onto the avatar: each FBX (Mixamo's "FBX Binary",
with or without skin) becomes one action on the avatar's armature, named
after the file, pushed down on its own NLA track (so the GLB export writes it
as a clip; Theater Puppet plays it by that name).

The bones match by name: Mixamo's mixamorig:Hips… are the names Rename to
Mixamo gives the avatar. Each bone takes the turn Mixamo's bone makes from its
rest pose, in the world (whatever either armature's own rolls, scale or
rotation); the hips also move, by as much as Mixamo's, scaled to the avatar's
hip height. Both rest poses should be a T-pose (Mixamo's is; the avatar's
after Rig's T-Pose). Bones Mixamo doesn't have (springs, eyes…) get no keys.

The imported FBX (armature, meshes, its own action) is deleted afterwards."""

import math
import os
import re

import bpy
from mathutils import Matrix, Quaternion

from . import analyse as an
from . import tpose

PREFIX = re.compile(r"^mixamorig\d*:", re.I)


def plain(name):
    return PREFIX.sub("", name)


def _rot(m):
    return m.to_3x3().normalized().to_quaternion()


def not_t_posed(arm):
    """The avatar's limbs that aren't in a T-pose at rest: [(bone, degrees off)]."""
    w = arm.matrix_world.to_3x3()
    out = []
    for name, want in tpose.TARGETS.items():
        b = arm.data.bones.get(name)
        if b is None:
            continue
        d = (w @ b.matrix_local.to_3x3().col[1]).normalized()
        off = d.angle(want)
        if off > math.radians(10):
            out.append((name, round(math.degrees(off))))
    return out


def _depth(b):
    return len(b.parent_recursive)


def _clear(arm, name):
    """An earlier import with that name: its action and NLA strip(s) gone."""
    ad = arm.animation_data
    if ad:
        for track in list(ad.nla_tracks):
            for s in list(track.strips):
                if s.action and s.action.name == name:
                    track.strips.remove(s)
            if not track.strips:
                ad.nla_tracks.remove(track)
    old = bpy.data.actions.get(name)
    if old is not None:
        bpy.data.actions.remove(old)


def import_fbx(context, path, arm=None, name=None):
    """One Mixamo FBX onto the avatar. Returns (action name, frames, bones keyed, [Mixamo bones the avatar lacks])."""
    arm = arm or an.find_armature(context)
    if arm is None:
        raise RuntimeError("No armature")
    name = name or os.path.splitext(os.path.basename(path))[0]
    scene = context.scene
    frame, start, end = scene.frame_current, scene.frame_start, scene.frame_end
    mode = arm.mode
    active = context.view_layer.objects.active
    if mode != "OBJECT":
        context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode="OBJECT")

    before = {k: set(getattr(bpy.data, k)) for k in ("objects", "armatures", "meshes", "materials", "actions", "images", "textures")}
    bpy.ops.import_scene.fbx(filepath=path)
    added = {k: set(getattr(bpy.data, k)) - v for k, v in before.items()}
    try:
        src = next((o for o in added["objects"] if o.type == "ARMATURE"), None)
        if src is None or not (src.animation_data and src.animation_data.action):
            raise RuntimeError(f"{os.path.basename(path)}: no animated armature in it")
        f0, f1 = (int(round(x)) for x in src.animation_data.action.frame_range)

        sbones = {plain(b.name): b.name for b in src.data.bones}
        tbones = sorted(arm.data.bones, key=_depth)
        mapped = [b for b in tbones if plain(b.name) in sbones]
        lacking = sorted(set(sbones) - {plain(b.name) for b in arm.data.bones} - {n for n in sbones if n.endswith("_End")})
        if len(mapped) < 10:
            raise RuntimeError(f"only {len(mapped)} bone(s) match Mixamo's: run Rename to Mixamo first")

        Ws, Wt = src.matrix_world, arm.matrix_world
        Wt_rot = _rot(Wt)
        Wt_inv3 = Wt.inverted().to_3x3()
        # Rest: each target bone's world rotation; Mixamo's, inverted
        t_rest_w = {b.name: _rot(Wt @ b.matrix_local) for b in mapped}
        s_rest_w_inv = {b.name: _rot(Ws @ src.data.bones[sbones[plain(b.name)]].matrix_local).inverted() for b in mapped}
        hips = arm.data.bones.get("Hips") or mapped[0]
        s_hips = src.data.bones[sbones[plain(hips.name)]]
        s_hips_rest = (Ws @ s_hips.matrix_local).translation
        ratio = (Wt @ hips.matrix_local).translation.z / max(s_hips_rest.z, 1e-4)

        # A hips bone connected to its parent (VRoid's, to Root) can't move:
        # Blender drops its location, and so does the export. Disconnected,
        # nothing moves at rest
        if hips.use_connect:
            # (Edit Mode moves the bones in memory: kept by name)
            hips_name = hips.name
            context.view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode="EDIT")
            arm.data.edit_bones[hips_name].use_connect = False
            bpy.ops.object.mode_set(mode="OBJECT")
            hips = arm.data.bones[hips_name]
            tbones = sorted(arm.data.bones, key=_depth)
            mapped = [b for b in tbones if plain(b.name) in sbones]

        _clear(arm, name)
        act = bpy.data.actions.new(name)
        act.use_fake_user = True
        ad = arm.animation_data or arm.animation_data_create()
        keep_action = ad.action
        ad.action = act
        for b in mapped:
            arm.pose.bones[b.name].rotation_mode = "QUATERNION"
        prev = {}
        is_mapped = {b.name for b in mapped}
        for f in range(f0, f1 + 1):
            scene.frame_set(f)
            pose = {}   # armature-space pose matrices, parents first
            for b in tbones:
                rel = b.matrix_local if b.parent is None else b.parent.matrix_local.inverted() @ b.matrix_local
                base = rel if b.parent is None else pose[b.parent.name] @ rel
                if b.name not in is_mapped:
                    pose[b.name] = base
                    continue
                sp = src.pose.bones[sbones[plain(b.name)]]
                turn = _rot(Ws @ sp.matrix) @ s_rest_w_inv[b.name]
                q_arm = Wt_rot.inverted() @ turn @ t_rest_w[b.name]
                if b == hips:
                    offset = (Ws @ sp.matrix).translation - s_hips_rest
                    pos = b.matrix_local.translation + Wt_inv3 @ (offset * ratio)
                    want = Matrix.Translation(pos) @ q_arm.to_matrix().to_4x4()
                    local = base.inverted() @ want
                    loc, q, _ = local.decompose()
                else:
                    q = _rot(base).inverted() @ q_arm
                    loc = None
                if b.name in prev:
                    q.make_compatible(prev[b.name])
                prev[b.name] = q
                pb = arm.pose.bones[b.name]
                pb.rotation_quaternion = q
                pb.keyframe_insert("rotation_quaternion", frame=f, group=b.name)
                if loc is not None:
                    pb.location = loc
                    pb.keyframe_insert("location", frame=f, group=b.name)
                    pose[b.name] = want
                else:
                    pose[b.name] = base @ q.to_matrix().to_4x4()
        # Its own NLA track, so the export writes it; the active action as it was
        ad.action = keep_action
        track = ad.nla_tracks.new()
        track.name = name
        track.strips.new(name, f0, act)
        track.mute = True    # the avatar's pose in Blender isn't taken over by it
        for b in mapped:
            pb = arm.pose.bones[b.name]
            pb.rotation_quaternion = Quaternion()
            pb.location = (0, 0, 0)
        return name, f1 - f0 + 1, len(mapped), lacking
    finally:
        for o in added["objects"]:
            bpy.data.objects.remove(o, do_unlink=True)
        # The FBX's own action has a fake user: gone anyway (or the GLB gets it too)
        for d in added["actions"]:
            if d.name in bpy.data.actions and bpy.data.actions[d.name] == d:
                bpy.data.actions.remove(d)
        for k in ("armatures", "meshes", "materials", "textures", "images"):
            coll = getattr(bpy.data, k)
            for d in added[k]:
                if d.name in coll and coll[d.name] == d and d.users == 0:
                    coll.remove(d)
        scene.frame_start, scene.frame_end = start, end
        scene.frame_set(frame)
        context.view_layer.objects.active = active
        if mode != "OBJECT" and context.view_layer.objects.active == arm:
            bpy.ops.object.mode_set(mode=mode)
