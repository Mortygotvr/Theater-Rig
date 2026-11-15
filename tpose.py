"""T-Pose: arms horizontal and straight, legs straight down, applied as the
new rest pose. Shape keys are kept: each one is re-made in the new pose
(Blender won't apply an armature to a mesh that has shape keys).

Does nothing when the model is already within TOLERANCE of a T-pose."""

import math

import bpy
from mathutils import Matrix, Vector

from . import analyse as an

TOLERANCE = math.radians(2.0)

# Mixamo bone -> direction it should point in a T-pose (Blender: +X is the
# model's left, -Y its front, +Z up)
TARGETS = {
    "LeftArm": Vector((1, 0, 0)), "LeftForeArm": Vector((1, 0, 0)), "LeftHand": Vector((1, 0, 0)),
    "RightArm": Vector((-1, 0, 0)), "RightForeArm": Vector((-1, 0, 0)), "RightHand": Vector((-1, 0, 0)),
    "LeftUpLeg": Vector((0, 0, -1)), "LeftLeg": Vector((0, 0, -1)),
    "RightUpLeg": Vector((0, 0, -1)), "RightLeg": Vector((0, 0, -1)),
}
ORDER = ["LeftUpLeg", "LeftLeg", "RightUpLeg", "RightLeg",
         "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand"]


def _direction(arm, pb):
    m = arm.matrix_world.to_3x3() @ pb.matrix.to_3x3()
    return (m @ Vector((0, 1, 0))).normalized()


def needed(arm):
    """[(bone, angle off its T-pose direction)] for bones out by more than TOLERANCE."""
    out = []
    for name in ORDER:
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        angle = _direction(arm, pb).angle(TARGETS[name])
        if angle > TOLERANCE:
            out.append((name, angle))
    return out


def _pose_to_t(arm):
    view = bpy.context.view_layer
    world_inv = arm.matrix_world.to_3x3().inverted()
    for name in ORDER:
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        view.update()
        current = _direction(arm, pb)
        rot = current.rotation_difference(TARGETS[name]).to_matrix()
        # The world-space turn, expressed in armature space, around the bone's head
        rot_arm = world_inv @ rot @ arm.matrix_world.to_3x3()
        head = pb.matrix.translation.copy()
        new = Matrix.Translation(head) @ rot_arm.to_4x4() @ Matrix.Translation(-head) @ pb.matrix
        pb.matrix = new
    view.update()


def _deformed_meshes(arm):
    return [o for o in bpy.data.objects if o.type == "MESH"
            and any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]


def _bake_mesh(obj):
    """Writes the posed shape of the mesh (and of each shape key) into the mesh,
    with only its armature modifier counting. The armature modifier then shows
    the new rest pose as no change."""
    others = [m for m in obj.modifiers if m.type != "ARMATURE" and m.show_viewport]
    for m in others:
        m.show_viewport = False
    try:
        keys = obj.data.shape_keys.key_blocks if obj.data.shape_keys else []
        depsgraph = bpy.context.evaluated_depsgraph_get()
        if not keys:
            ev = obj.evaluated_get(depsgraph)
            co = [v.co.copy() for v in ev.data.vertices]
            for v, c in zip(obj.data.vertices, co):
                v.co = c
            return
        saved = (obj.show_only_shape_key, obj.active_shape_key_index)
        obj.show_only_shape_key = True
        posed = []
        for i in range(len(keys)):
            obj.active_shape_key_index = i
            depsgraph.update()
            ev = obj.evaluated_get(depsgraph)
            posed.append([v.co.copy() for v in ev.data.vertices])
        obj.show_only_shape_key, obj.active_shape_key_index = saved
        for key, co in zip(keys, posed):
            for d, c in zip(key.data, co):
                d.co = c
        for v, c in zip(obj.data.vertices, posed[0]):
            v.co = c
    finally:
        for m in others:
            m.show_viewport = True


def _apply_pose_as_rest(arm):
    view = bpy.context.view_layer
    pose = {pb.name: pb.matrix.copy() for pb in arm.pose.bones}
    prev = view.objects.active
    view.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for eb in arm.data.edit_bones:
        if eb.name in pose:
            eb.matrix = pose[eb.name]
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    view.objects.active = prev


def t_pose(context=None):
    """Returns (armature, [(bone, degrees it was off)]); empty when already a T-pose."""
    arm = an.find_armature(context)
    if arm is None:
        return None, []
    off = needed(arm)
    if not off:
        return arm, []
    view = bpy.context.view_layer
    active = view.objects.active
    if active is not None and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    _pose_to_t(arm)
    for obj in _deformed_meshes(arm):
        _bake_mesh(obj)
    _apply_pose_as_rest(arm)
    return arm, [(n, math.degrees(a)) for n, a in off]
