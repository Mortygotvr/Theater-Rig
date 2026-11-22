"""Export Animation: a skeleton's actions as animation GLBs for Theater
Puppet's Animation folder, where any avatar plays them (retarget.rs). Any
armature with Mixamo's bone names (Hips, Spine, LeftArm…) in a T-pose: an
imported Mixamo one, the avatar's, a copy of it. Each action is its own GLB,
named after it: the skeleton (no mesh) and that one clip, with its contact
frames. The avatar's GLB (Export GLB) has no animation.

The actions: its active one and those on its NLA tracks. Not the VRM
add-on's "T-Pose"."""

import os
import re

import bpy

from . import contacts
from . import tpose

SKIP = {"T-Pose"}


def _fcurves(action):
    """Every F-curve of the action (Blender 5's layered actions, or older)."""
    out = []
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                out.extend(bag.fcurves)
    if not out and hasattr(action, "fcurves"):
        out = list(action.fcurves)
    return out


def _moves_bones(action, arm):
    names = {b.name for b in arm.data.bones}
    for fc in _fcurves(action):
        m = re.match(r'pose\.bones\["(.+?)"\]', fc.data_path)
        if m and m.group(1) in names:
            return True
    return False


MIXAMO_BONES = {"Hips", "Spine", "LeftArm", "RightUpLeg"}


def is_mixamo(arm):
    return arm is not None and arm.type == "ARMATURE" and MIXAMO_BONES <= {b.name for b in arm.data.bones}


def not_t_posed(arm):
    """Its limbs not in a T-pose at rest: [(bone, degrees off)] (Puppet
    turns each bone as much as here from rest: the rest must be a T-pose)."""
    import math
    w = arm.matrix_world.to_3x3()
    out = []
    for name, want in tpose.TARGETS.items():
        b = arm.data.bones.get(name)
        if b is None:
            continue
        off = (w @ b.matrix_local.to_3x3().col[1]).normalized().angle(want)
        if off > math.radians(10):
            out.append((name, round(math.degrees(off))))
    return out


def actions_of(arm):
    """Its actions: the active one, then those on its NLA tracks."""
    out = []
    ad = arm.animation_data
    if ad and ad.action:
        out.append(ad.action)
    if ad:
        for track in ad.nla_tracks:
            for s in track.strips:
                if s.action:
                    out.append(s.action)
    seen, unique = set(), []
    for a in out:
        if a.name not in seen and a.name not in SKIP and _moves_bones(a, arm):
            seen.add(a.name)
            unique.append(a)
    return unique


def _name_animation(glb, name):
    """Names the GLB's animation(s) `name` (the exporter calls an active
    action's "Animation"): its JSON chunk rewritten, padded to 4 bytes."""
    import json
    import struct
    with open(glb, "rb") as f:
        data = f.read()
    n = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20:20 + n])
    for a in gltf.get("animations", []):
        a["name"] = name
    js = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    js += b" " * (-len(js) % 4)
    rest = data[20 + n:]
    body = struct.pack("<I", len(js)) + b"JSON" + js + rest
    with open(glb, "wb") as f:
        f.write(data[:8] + struct.pack("<I", 12 + len(body)) + body)


def file_name(action):
    return re.sub(r'[<>:"/\\|?*]', "_", action.name).strip() or "animation"


def export_actions(context, arm, folder, actions=None):
    """Each action as <folder>/<its name>.glb. Returns [(action name, path)]."""
    os.makedirs(folder, exist_ok=True)
    actions = actions if actions is not None else actions_of(arm)
    view = context.view_layer
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    selected = [o for o in view.objects if o.select_get()]
    active = view.objects.active
    ad = arm.animation_data or arm.animation_data_create()
    keep_action, keep_nla = ad.action, ad.use_nla
    done = []
    try:
        for o in view.objects:
            o.select_set(o == arm)
        view.objects.active = arm
        ad.use_nla = False   # the action alone, no track blended in
        for act in actions:
            ad.action = act
            path = os.path.join(folder, file_name(act) + ".glb")
            # The hook names the clip and gives it its contacts (it'd be "Animation")
            contacts.export_as = (act.name, act)
            try:
                bpy.ops.export_scene.gltf(
                    filepath=path,
                    export_format="GLB",
                    use_selection=True,
                    export_extras=True,
                    export_skins=False,
                    export_morph=False,
                    export_animations=True,
                    export_animation_mode="ACTIVE_ACTIONS",
                    export_yup=True,
                )
            finally:
                contacts.export_as = None
            _name_animation(path, act.name)
            done.append((act.name, path))
    finally:
        ad.action = keep_action
        ad.use_nla = keep_nla
        for o in [o for o in view.objects if o is not None]:
            o.select_set(o in selected)
        view.objects.active = active
    return done
