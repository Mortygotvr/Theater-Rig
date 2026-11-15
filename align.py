"""Align Bones: each bone points at its child, with one roll convention, so IK
and animations get predictable axes.

- Direction (local Y): towards the next bone of its chain (upper arm ->
  forearm, hand -> middle finger, spine -> neck...), or its only child.
- Leaves keep their length: the head points up, eyes and toes forward,
  other leaves continue their parent's direction.
- Roll (local Z): towards the front of the model (-Y in Blender), or up for
  bones that point forward or back.

The mesh doesn't move: only the bones' rest orientation changes."""

import bpy
from mathutils import Vector

from . import analyse as an

FRONT = Vector((0, -1, 0))
UP = Vector((0, 0, 1))

# Mixamo bone -> the child it should point at
NEXT = {"Hips": "Spine", "Spine": "Spine1", "Spine1": "Spine2", "Spine2": "Neck", "Neck": "Head"}
for S in ("Left", "Right"):
    NEXT.update({
        f"{S}Shoulder": f"{S}Arm", f"{S}Arm": f"{S}ForeArm", f"{S}ForeArm": f"{S}Hand",
        f"{S}Hand": f"{S}HandMiddle1",
        f"{S}UpLeg": f"{S}Leg", f"{S}Leg": f"{S}Foot", f"{S}Foot": f"{S}ToeBase",
    })
    for F in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
        NEXT[f"{S}Hand{F}1"] = f"{S}Hand{F}2"
        NEXT[f"{S}Hand{F}2"] = f"{S}Hand{F}3"

POINT_UP = {"Head"}
POINT_FRONT = {"LeftEye", "RightEye", "LeftToeBase", "RightToeBase"}
MIN_LEN = 1e-4


def _target(eb):
    wanted = NEXT.get(eb.name)
    if wanted:
        child = next((c for c in eb.children if c.name == wanted), None)
        if child is None:
            # Not a direct child (a twist bone in between): any descendant of that name
            child = next((c for c in eb.children_recursive if c.name == wanted), None)
        if child is not None:
            return child.head
    if len(eb.children) == 1:
        return eb.children[0].head
    return None


def align_bones(context=None):
    arm = an.find_armature(context)
    if arm is None:
        return None, 0
    view = bpy.context.view_layer
    prev_active, prev_mode = view.objects.active, (view.objects.active.mode if view.objects.active else "OBJECT")
    if prev_active and prev_mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    view.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    changed = 0
    try:
        ebs = arm.data.edit_bones
        # Parents first, so a leaf can follow its parent's new direction
        order = sorted(ebs, key=lambda b: len(b.parent_recursive))
        for eb in order:
            length = max(eb.length, MIN_LEN * 10)
            target = _target(eb)
            if eb.name in POINT_UP:
                tail = eb.head + UP * length
            elif eb.name in POINT_FRONT:
                tail = eb.head + FRONT * length
            elif target is not None and (target - eb.head).length > MIN_LEN:
                tail = target.copy()
            elif not eb.children and eb.parent is not None:
                tail = eb.head + (eb.parent.tail - eb.parent.head).normalized() * length
            else:
                tail = eb.tail.copy()
            direction = (tail - eb.head).normalized()
            if (tail - eb.tail).length > 1e-6:
                # Children connected to this bone would be dragged along: keep them put
                for c in eb.children:
                    c.use_connect = False
                eb.tail = tail
            eb.align_roll(UP if abs(direction.dot(FRONT)) > 0.9 else FRONT)
            changed += 1
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        if prev_active is not None:
            view.objects.active = prev_active
    return arm, changed
