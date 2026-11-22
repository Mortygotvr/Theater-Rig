"""Mixamo's Collada (.dae) into Blender (Blender 5 reads no Collada): the
skeleton as an armature at its T-pose, the animation as an action. Mixamo's
DAE: Y up, centimetres, each bone's local matrix baked per frame; its T-pose
is only in the skin's bind matrices, so it must be downloaded "With Skin"
(without, a bone's rest is the animation's first frame). Meshes aren't read:
the skeleton and its motion are what Export Animation needs."""

import math
import os
import xml.etree.ElementTree as ET

import bpy
from mathutils import Matrix

NS = "{http://www.collada.org/2005/11/COLLADASchema}"
# Y up (Collada) to Z up (Blender): +90 degrees about X
Y_TO_Z = Matrix.Rotation(math.radians(90), 4, "X")


def _floats(el):
    return [float(x) for x in (el.text or "").split()] if el is not None else []


def _matrix(v, unit):
    m = Matrix([v[0:4], v[4:8], v[8:12], v[12:16]])   # row by row
    m.translation = m.translation * unit
    return m


def _plain(name):
    from .mixamo import plain
    return plain(name)


def read(context, path):
    """The DAE as an armature (named after the file) with its action. Returns the armature."""
    name = os.path.splitext(os.path.basename(path))[0]
    root = ET.parse(path).getroot()
    unit_el = root.find(f".//{NS}unit")
    unit = float(unit_el.get("meter", "1")) if unit_el is not None else 1.0
    up = root.find(f".//{NS}up_axis")
    if up is not None and up.text.strip() != "Y_UP":
        raise RuntimeError(f"{os.path.basename(path)}: {up.text.strip()} (Mixamo's DAE is Y_UP)")

    # The T-pose: each joint's bind matrix
    binds = {}
    for skin in root.iter(f"{NS}skin"):
        sources = {s.get("id"): s for s in skin.findall(f"{NS}source")}
        joints = skin.find(f"{NS}joints")
        if joints is None:
            continue
        inputs = {i.get("semantic"): i.get("source", "").lstrip("#") for i in joints.findall(f"{NS}input")}
        js, ms = sources.get(inputs.get("JOINT")), sources.get(inputs.get("INV_BIND_MATRIX"))
        if js is None or ms is None:
            continue
        names = (js.find(f".//{NS}Name_array").text or "").split()
        mats = _floats(ms.find(f".//{NS}float_array"))
        for i, n in enumerate(names):
            if n not in binds and len(mats) >= (i + 1) * 16:
                binds[n] = _matrix(mats[i * 16:(i + 1) * 16], unit).inverted()
    if not binds:
        raise RuntimeError(f"{os.path.basename(path)}: no T-pose in it: download it from Mixamo \"With Skin\"")

    # The joints, parents first: (id, name, parent index, world at rest in Blender's space)
    scene = root.find(f".//{NS}visual_scene")
    joints = []

    def walk(el, parent):
        for c in el.findall(f"{NS}node"):
            if c.get("type") != "JOINT":
                continue
            raw = c.get("name") or c.get("id") or ""
            if raw in binds:
                world = binds[raw]
            else:
                own = c.find(f"{NS}matrix")
                local = _matrix(_floats(own), unit) if own is not None else Matrix()
                world = (joints[parent][3] if parent is not None else Matrix()) @ local
            joints.append((c.get("id"), _plain(raw), parent, world))
            walk(c, len(joints) - 1)
    walk(scene, None)
    if not joints:
        raise RuntimeError(f"{os.path.basename(path)}: no skeleton")
    rest = [Y_TO_Z @ w for _, _, _, w in joints]

    # The animation: each joint's local matrices per frame
    by_id = {j[0]: i for i, j in enumerate(joints)}
    tracks = {}
    for anim in root.iter(f"{NS}animation"):
        sources = {s.get("id"): s for s in anim.findall(f"{NS}source")}
        samplers = {s.get("id"): s for s in anim.findall(f"{NS}sampler")}
        for ch in anim.findall(f"{NS}channel"):
            target = ch.get("target", "")
            jid, _, what = target.partition("/")
            if jid not in by_id or not (what.startswith("matrix") or what == "transform"):
                continue
            smp = samplers.get(ch.get("source", "").lstrip("#"))
            if smp is None:
                continue
            ins = {i.get("semantic"): i.get("source", "").lstrip("#") for i in smp.findall(f"{NS}input")}
            times = _floats(sources[ins["INPUT"]].find(f".//{NS}float_array"))
            vals = _floats(sources[ins["OUTPUT"]].find(f".//{NS}float_array"))
            n = min(len(times), len(vals) // 16)
            tracks[by_id[jid]] = (times[:n], [_matrix(vals[k * 16:(k + 1) * 16], unit) for k in range(n)])
    if not tracks:
        raise RuntimeError(f"{os.path.basename(path)}: no animation in it")

    # The armature, at the T-pose
    data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, data)
    context.scene.collection.objects.link(arm)
    view = context.view_layer
    for o in view.objects:
        o.select_set(False)
    arm.select_set(True)
    view.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = []
    for i, (_, bname, parent, _) in enumerate(joints):
        eb = data.edit_bones.new(bname)
        kids = [k for k, j in enumerate(joints) if j[2] == i]
        length = (rest[kids[0]].translation - rest[i].translation).length if kids else 0.0
        eb.head = (0, 0, 0)
        eb.tail = (0, max(length, 0.03), 0)
        eb.matrix = rest[i].normalized()
        if parent is not None:
            eb.parent = ebs[parent]
        ebs.append(eb)
    bpy.ops.object.mode_set(mode="OBJECT")

    # The action: each bone's pose from its rest, per frame (Mixamo's 30 fps)
    all_times = sorted({t for ts, _ in tracks.values() for t in ts})
    step = min((b - a for a, b in zip(all_times, all_times[1:]) if b - a > 1e-6), default=1 / 30)
    fps = max(1, round(1 / step))
    context.scene.render.fps, context.scene.render.fps_base = fps, 1.0
    act = bpy.data.actions.new(name)
    arm.animation_data_create().action = act
    t0 = all_times[0]
    for i, (_, bname, parent, _) in enumerate(joints):
        if i not in tracks:
            continue
        pb = arm.pose.bones[bname]
        pb.rotation_mode = "QUATERNION"
        rest_local = rest[i] if parent is None else rest[parent].inverted() @ rest[i]
        prev = None
        for t, m in zip(*tracks[i]):
            local = Y_TO_Z @ m if parent is None else m
            loc, rot, _ = (rest_local.normalized().inverted() @ local).decompose()
            if prev is not None:
                rot.make_compatible(prev)
            prev = rot
            f = 1 + round((t - t0) * fps)
            pb.location, pb.rotation_quaternion = loc, rot
            pb.keyframe_insert("location", frame=f, group=bname)
            pb.keyframe_insert("rotation_quaternion", frame=f, group=bname)
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix()
    context.scene.frame_start = 1
    context.scene.frame_end = 1 + round((all_times[-1] - t0) * fps)
    return arm
