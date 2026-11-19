"""Make Cloth Bones: spring chains and their weights for a part of a mesh (a
skirt, a cape, long hair), made in one go, then adjusted by hand.

You select the part (its faces in Edit Mode, or a material); this finds the
edge it hangs from (its top) and its free edge (its bottom), splits it into
columns (around the body for a ring like a skirt, across it for a sheet like
a cape) and rows, and puts a chain down the middle of each column, named by
the convention (spring_<kind>_<n>_<i>), hanging from a body bone (the
nearest, or the one given).

Weights: each vertex of the part blends between its two nearest bones down
its column and toward the next column (no seams); the band along the top
keeps fading into its body bone's weights; nothing outside the part changes.

Each cloth is kept on the armature as `theater_cloth` (glTF extras, like
`theater_tiles`): {name: {kind, shape: "ring" | "sheet", chains: [roots, in
order around or across], mesh, columns, rows, parent}}. Making the same name
again replaces its bones and weights (never other bones).
"""

import json
import math

import bpy
from mathutils import Vector

PROP = "theater_cloth"
KINDS = ["skirt", "cloth", "hair", "ribbon", "tail", "misc"]
# Body bones a cloth can hang from (the nearest one to its top, along the
# bone, by default)
BODY = ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "LeftUpLeg", "RightUpLeg", "LeftShoulder", "RightShoulder"]
# The top band (in rows) that fades into the body bone's weights
TOP_BAND = 0.6
# The tip past the hem: the last bone needs a child for its length (Puppet)
TIP = 0.03


def cloths(arm):
    try:
        return json.loads(arm.get(PROP, "{}"))
    except (TypeError, ValueError):
        return {}


def _save(arm, data):
    arm[PROP] = json.dumps(data)


def _vertex_sets(obj, material=None):
    """The part: the selected vertices (their faces, as Edit Mode left them),
    or the vertices of a material's faces."""
    mesh = obj.data
    if material:
        slots = {i for i, s in enumerate(obj.material_slots) if s.material and s.material.name == material}
        return sorted({v for p in mesh.polygons if p.material_index in slots for v in p.vertices})
    return [v.index for v in mesh.vertices if v.select]


def _next_number(arm, kind, taken_chains):
    used = set()
    for b in arm.data.bones:
        parts = b.name.split("_")
        if len(parts) >= 4 and parts[0] == "spring" and parts[1] == kind and parts[2].isdigit():
            if f"spring_{kind}_{parts[2]}" not in taken_chains:
                used.add(int(parts[2]))
    n = 1
    while n in used:
        n += 1
    return n


def plan(points, columns, rows, ring=None):
    """Where the chains go, from the part's points (armature space, +Z up):
    (shape, joints per column [rows + 1 points, top to hem], each point's
    (column, row) coordinates). Pure geometry, for the tests."""
    zs = [p.z for p in points]
    top, bottom = max(zs), min(zs)
    height = max(top - bottom, 1e-6)
    rim = [p for p in points if p.z >= top - height * 0.08]
    cx = sum(p.x for p in rim) / len(rim)
    cy = sum(p.y for p in rim) / len(rim)
    # Around the top's middle: a ring when the part goes nearly all around
    angles = sorted(math.atan2(p.y - cy, p.x - cx) for p in points)
    gaps = [b - a for a, b in zip(angles, angles[1:])] + [angles[0] + 2 * math.pi - angles[-1]]
    if ring is None:
        ring = max(gaps) < math.radians(90)
    if ring:
        # Start where the part has its widest gap (none: anywhere)
        start = angles[gaps.index(max(gaps))] + max(gaps) / 2 if max(gaps) > 1e-3 else 0.0

        def across(p):
            a = (math.atan2(p.y - cy, p.x - cx) - start) % (2 * math.pi)
            return a / (2 * math.pi) * columns
    else:
        # Across: the top's widest direction (its points' spread in X and Y)
        xs, ys = [p.x for p in rim], [p.y for p in rim]
        sxx = sum((x - cx) ** 2 for x in xs)
        syy = sum((y - cy) ** 2 for y in ys)
        sxy = sum((x - cx) * (y - cy) for x, y in zip(xs, ys))
        angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
        axis = Vector((math.cos(angle), math.sin(angle), 0.0))
        us = [(p - Vector((cx, cy, 0))).dot(axis) for p in points]
        lo, hi = min(us), max(us)
        span = max(hi - lo, 1e-6)

        def across(p):
            return min(max(((p - Vector((cx, cy, 0))).dot(axis) - lo) / span, 0.0), 0.999999) * columns

    coords = [(across(p), (top - p.z) / height * rows) for p in points]
    joints = []
    for c in range(columns):
        mine = [(p, r) for p, (u, r) in zip(points, coords) if c <= u < c + 1]
        if not mine:
            joints.append(None)
            continue
        col = []
        for k in range(rows + 1):
            band = [p for p, r in mine if abs(r - k) <= 0.5]
            if not band:
                # The nearest row's points
                near = min(mine, key=lambda pr: abs(pr[1] - k))[1]
                band = [p for p, r in mine if abs(r - near) <= 0.5]
            centre = sum(band, Vector()) / len(band)
            col.append(centre)
        joints.append(col)
    return ("ring" if ring else "sheet"), joints, coords


def weights_for(u, r, columns, rows, ring):
    """A point's weights: {(column, bone): w} and how much stays on the body."""
    out = {}
    t = min(max(r - 0.5, 0.0), rows - 1.0)
    i0 = int(math.floor(t))
    fr = t - i0
    i1 = min(i0 + 1, rows - 1)
    s = u - 0.5
    if ring:
        j0 = int(math.floor(s)) % columns
        fc = s - math.floor(s)
        j1 = (j0 + 1) % columns
    else:
        s = min(max(s, 0.0), columns - 1.0)
        j0 = int(math.floor(s))
        fc = s - j0
        j1 = min(j0 + 1, columns - 1)
    for (j, wc) in ((j0, 1 - fc), (j1, fc)):
        for (i, wr) in ((i0, 1 - fr), (i1, fr)):
            if wc * wr > 1e-6:
                out[(j, i)] = out.get((j, i), 0.0) + wc * wr
    body = max(0.0, 1.0 - r / TOP_BAND)
    return out, body


def remove(arm, name, objects=None):
    """Takes a cloth's bones, vertex groups and record away."""
    data = cloths(arm)
    cloth = data.pop(name, None)
    if cloth is None:
        return False
    prefixes = tuple(f"{root[:-2]}_" for root in cloth["chains"] if root)
    view = bpy.context.view_layer
    was = view.objects.active
    mode = was.mode if was else "OBJECT"
    if was and mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    view.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for eb in [b for b in arm.data.edit_bones if b.name.startswith(prefixes)]:
        arm.data.edit_bones.remove(eb)
    bpy.ops.object.mode_set(mode="OBJECT")
    for obj in objects or [o for o in bpy.data.objects if o.type == "MESH"]:
        for g in [g for g in obj.vertex_groups if g.name.startswith(prefixes)]:
            obj.vertex_groups.remove(g)
    _save(arm, data)
    if was:
        view.objects.active = was
        if mode != "OBJECT":
            bpy.ops.object.mode_set(mode=mode)
    return True


def make(arm, obj, columns=8, rows=4, kind="skirt", parent="", material=None, name=""):
    """Makes (or makes again) a cloth's chains and weights on `obj`'s part.
    Returns (name, shape, chains made)."""
    view = bpy.context.view_layer
    # Edit Mode's selection is in the mesh once out of it
    if obj.mode != "OBJECT":
        view.objects.active = obj
        bpy.ops.object.mode_set(mode="OBJECT")
    columns, rows = max(2, int(columns)), max(1, int(rows))
    kind = kind if kind in KINDS else "misc"
    name = name.strip() or ""
    data = cloths(arm)
    if name and name in data:
        remove(arm, name, [obj])
        data = cloths(arm)
    verts = _vertex_sets(obj, material)
    if len(verts) < columns * 2:
        raise ValueError("Select the part first (its faces in Edit Mode), or pick its material")
    to_arm = arm.matrix_world.inverted() @ obj.matrix_world
    points = [to_arm @ obj.data.vertices[i].co for i in verts]
    shape, joints, coords = plan(points, columns, rows)
    if any(j is None for j in joints):
        raise ValueError(f"{columns} columns is too many for this part: some have no vertices (try fewer)")

    # The body bone it hangs from: the nearest to its top
    bones = arm.data.bones
    top = max(p.z for p in points)
    rim = [p for p, (_, r) in zip(points, coords) if r <= 0.15 * rows] or points
    rim_mid = sum(rim, Vector()) / len(rim)
    if not parent or parent not in bones:
        body = [bones[b] for b in BODY if b in bones] or [b for b in bones if not b.name.startswith("spring_")]
        # (Along each bone, head to tail: a bone's head alone can be the
        # wrong one's nearest, like the head's for a cape at the chest)
        def gap(b):
            ab = b.tail_local - b.head_local
            t = max(0.0, min(1.0, (rim_mid - b.head_local).dot(ab) / ab.length_squared)) if ab.length_squared > 1e-10 else 0.0
            return (rim_mid - (b.head_local + ab * t)).length

        parent = min(body, key=gap).name

    # The bones
    n0 = _next_number(arm, kind, set())
    chains = []
    was = view.objects.active
    view.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = arm.data.edit_bones
    for c, col in enumerate(joints):
        chain = f"spring_{kind}_{n0 + c}"
        prev = ebs.get(parent)
        for i in range(rows + 1):
            eb = ebs.new(f"{chain}_{i}")
            eb.head = col[i]
            if i < rows:
                eb.tail = col[i + 1]
            else:
                # The tip past the hem, so the last bone has its length
                d = col[i] - col[i - 1]
                eb.tail = col[i] + (d.normalized() if d.length > 1e-6 else Vector((0, 0, -1))) * TIP
            if (eb.tail - eb.head).length < 1e-4:
                eb.tail = eb.head + Vector((0, 0, -0.01))
            eb.parent = prev
            eb.use_connect = i > 0
            eb.use_deform = i < rows
            prev = eb
        chains.append(f"{chain}_0")
    bpy.ops.object.mode_set(mode="OBJECT")

    # The weights
    groups = {}
    for c in range(columns):
        for i in range(rows):
            gname = f"spring_{kind}_{n0 + c}_{i}"
            groups[(c, i)] = obj.vertex_groups.get(gname) or obj.vertex_groups.new(name=gname)
    spring_groups = set(groups.values())
    pgroup = obj.vertex_groups.get(parent) or obj.vertex_groups.new(name=parent)
    for vi, (u, r) in zip(verts, coords):
        ws, body = weights_for(u, r, columns, rows, shape == "ring")
        v = obj.data.vertices[vi]
        # The body's share (the top band): its own body weights scaled to it,
        # or the parent bone's when it has none; the rest the chains'
        existing = [(obj.vertex_groups[g.group], g.weight) for g in v.groups if obj.vertex_groups[g.group] not in spring_groups]
        total = sum(w for _, w in existing)
        for grp, w in existing:
            if body > 0.0 and total > 1e-6:
                grp.add([vi], w / total * body, "REPLACE")
            else:
                grp.remove([vi])
        if body > 0.0 and total <= 1e-6:
            pgroup.add([vi], body, "REPLACE")
        for key, w in ws.items():
            groups[key].add([vi], w * (1.0 - body), "REPLACE")
    # The mesh follows the armature
    if not any(m.type == "ARMATURE" and m.object == arm for m in obj.modifiers):
        obj.modifiers.new("Armature", "ARMATURE").object = arm

    name = name or f"{kind}_{n0}"
    data[name] = {"kind": kind, "shape": shape, "chains": chains, "mesh": obj.name, "columns": columns, "rows": rows, "parent": parent}
    _save(arm, data)
    if was:
        view.objects.active = was
    return name, shape, chains
