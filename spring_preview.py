"""Spring preview: the avatar's spring chains swinging in Blender as Theater
Puppet swings them (Theater-Puppet/src/springs.rs, the same steps), to tune
them before exporting.

- The chains are the convention's: bones spring_<kind>_<n>_<i> (Rename
  Springs makes them), the settings on each chain's root (_0) as custom
  properties: spring_stiffness, spring_gravity, spring_drag, spring_radius
  (what Export puts in the GLB). Missing ones are Puppet's defaults.
- Each joint's tail keeps its inertia, springs back toward its rest
  direction, falls with gravity, keeps its length, and is pushed out of the
  colliders: capsules along the Mixamo bones, as thick as the body's mesh
  there (the skin material's, else all but the hair), as Puppet builds them.
- It runs in the world: moving the armature, posing its bones or playing an
  animation swings them. "Sway the body" turns the hips back and forth.
  Stopping puts every bone back as it was.
"""

import math
import time

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Quaternion, Vector

LEAF_LENGTH = 0.07
DEFAULTS = {"stiffness": 1.0, "gravity": 0.0, "drag": 0.4, "radius": 0.02}

# Bones that get a collider, and the bone each one runs to (springs.rs)
COLLIDER_BONES = [
    ("Head", ["HeadTop_End"]), ("Neck", ["Head"]), ("Spine", ["Spine1"]), ("Spine1", ["Spine2"]),
    ("Spine2", ["Neck"]), ("Hips", ["Spine"]), ("LeftShoulder", ["LeftArm"]), ("RightShoulder", ["RightArm"]),
    ("LeftHand", ["LeftHandMiddle1"]), ("RightHand", ["RightHandMiddle1"]), ("LeftArm", ["LeftForeArm"]),
    ("LeftForeArm", ["LeftHand"]), ("RightArm", ["RightForeArm"]), ("RightForeArm", ["RightHand"]),
    ("LeftUpLeg", ["LeftLeg"]), ("LeftLeg", ["LeftFoot"]), ("RightUpLeg", ["RightLeg"]), ("RightLeg", ["RightFoot"]),
]


def chain_of(name):
    """spring_<kind>_<n>_<i> -> (spring_<kind>_<n>, i), or None."""
    if not name.startswith("spring_"):
        return None
    chain, _, i = name.rpartition("_")
    if not i.isdigit() or chain.count("_") < 2:
        return None
    return chain, int(i)


def roots(arm):
    """The chains' root bones (spring_…_0), in name order."""
    return sorted((b for b in arm.data.bones if (c := chain_of(b.name)) and c[1] == 0), key=lambda b: b.name)


def ensure_settings(arm):
    """Every chain root has its four settings (Puppet's defaults where missing)."""
    for bone in roots(arm):
        for k, v in DEFAULTS.items():
            if f"spring_{k}" not in bone.keys():
                bone[f"spring_{k}"] = v


def _closest_on_segment(p, a, b):
    ab = b - a
    l2 = ab.length_squared
    t = max(0.0, min(1.0, (p - a).dot(ab) / l2)) if l2 > 1e-10 else 0.0
    return a + ab * t


def _avatar_meshes(arm):
    return [o for o in bpy.data.objects if o.type == "MESH" and (o.parent == arm or any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers))]


def colliders_of(arm):
    """Puppet's capsules: [(bone, base, tip (in the bone's own rest frame), radius)], armature space."""
    to_arm = arm.matrix_world.inverted()
    # Each vertex: its dominant bone, where it is at rest (armature space), on skin or hair
    by_bone = {}
    for obj in _avatar_meshes(arm):
        mesh = obj.data
        names = [g.name for g in obj.vertex_groups]
        mats = [(s.material.name.lower() if s.material else "") for s in obj.material_slots]
        kind = {}
        for p in mesh.polygons:
            m = mats[p.material_index] if p.material_index < len(mats) else ""
            k = "skin" if "skin" in m else "hair" if "hair" in m else "other"
            for v in p.vertices:
                if kind.get(v) != "skin":
                    kind[v] = k
        to = to_arm @ obj.matrix_world
        for v in mesh.vertices:
            if not v.groups:
                continue
            g = max(v.groups, key=lambda x: x.weight)
            if g.group >= len(names):
                continue
            by_bone.setdefault(names[g.group], []).append((to @ v.co, kind.get(v.index, "other")))
    out = []
    bones = arm.data.bones
    for name, ends in COLLIDER_BONES:
        bone = bones.get(name)
        moved_all = by_bone.get(name, [])
        if bone is None:
            continue
        moved = [p for p, k in moved_all if k == "skin"]
        skin = len(moved) >= 8
        if not skin:
            moved = [p for p, k in moved_all if k != "hair"]
        if len(moved) < 8:
            moved = [p for p, _ in moved_all]
        if len(moved) < 8:
            continue
        a = bone.head_local.copy()
        end = next((bones[e] for e in ends if e in bones), None)
        b = end.head_local.copy() if end else sum(moved, Vector()) / len(moved)
        d = sorted((p - _closest_on_segment(p, a, b)).length for p in moved)
        radius = d[len(d) // 2] * (1.0 if skin else 0.85)
        rot = bone.matrix_local.to_3x3().inverted()
        out.append((name, Vector(), rot @ (b - a), radius))
    # The chest's sides: one more across it, from arm to arm
    chest = bones.get("Spine2") or bones.get("Spine1")
    l, r = bones.get("LeftArm"), bones.get("RightArm")
    thick = next((c[3] for c in out if chest and c[0] == chest.name), None)
    if chest and l and r and thick:
        rot = chest.matrix_local.to_3x3().inverted()
        down = Vector((0, 0, -thick * 0.5))
        lp, rp = l.head_local.lerp(r.head_local, 0.12) + down, r.head_local.lerp(l.head_local, 0.12) + down
        out.append((chest.name, rot @ (lp - chest.head_local), rot @ (rp - chest.head_local), thick * 0.85))
    return out


class Joint:
    __slots__ = ("name", "root", "axis", "length", "rel_rest", "tail", "prev_tail", "basis")


class Preview:
    def __init__(self, arm):
        self.arm = arm
        bones = arm.data.bones
        ensure_settings(arm)
        # Parents before children
        order = []

        def walk(b):
            order.append(b)
            for c in b.children:
                walk(c)

        for b in bones:
            if b.parent is None:
                walk(b)
        self.joints = []
        for bone in order:
            c = chain_of(bone.name)
            if not c:
                continue
            head = bone.head_local
            child = bone.children[0] if bone.children else None
            if child is not None:
                tail = child.head_local
            else:
                up = (head - bone.parent.head_local).normalized() if bone.parent else Vector((0, 0, -1))
                tail = head + up * LEAF_LENGTH
            if (tail - head).length < 1e-5:
                continue
            j = Joint()
            j.name = bone.name
            j.root = f"{c[0]}_0"
            j.axis = (bone.matrix_local.to_3x3().inverted() @ (tail - head)).normalized()
            j.length = (tail - head).length
            j.rel_rest = (bone.parent.matrix_local.inverted() @ bone.matrix_local) if bone.parent else bone.matrix_local.copy()
            j.basis = Matrix.Identity(4)
            self.joints.append(j)
        self.colliders = colliders_of(arm)
        # What to put back when it stops
        names = [j.name for j in self.joints] + (["Hips"] if "Hips" in arm.pose.bones else [])
        self.saved = {n: arm.pose.bones[n].matrix_basis.copy() for n in names}
        self.started = time.perf_counter()
        self.last = self.started
        self.reset()

    def settings(self, root):
        bone = self.arm.data.bones.get(root)
        return {k: float(bone.get(f"spring_{k}", v)) if bone else v for k, v in DEFAULTS.items()}

    def _posed(self, name, computed):
        """A bone's matrix now (armature space): one moved this step, or as Blender has it."""
        return computed[name] if name in computed else self.arm.pose.bones[name].matrix

    def reset(self):
        """At rest, still."""
        W = self.arm.matrix_world
        computed = {}
        for j in self.joints:
            parent = self.arm.data.bones[j.name].parent
            M = (self._posed(parent.name, computed) @ j.rel_rest) if parent else j.rel_rest
            computed[j.name] = M
            head = W @ M.translation
            j.tail = head + (W.to_3x3() @ (M.to_3x3() @ j.axis)).normalized() * j.length * W.to_scale()[0]
            j.prev_tail = j.tail.copy()

    def capsules(self, thick=1.0):
        """The colliders now: (a, b, radius), world space."""
        W = self.arm.matrix_world
        s = W.to_scale()[0]
        out = []
        for name, base, tip, r in self.colliders:
            M = self.arm.pose.bones[name].matrix
            out.append((W @ (M @ base), W @ (M.translation + M.to_3x3() @ tip), r * s * max(thick, 0.0)))
        return out

    def step(self, dt, thick=1.0):
        """`dt` seconds later: the spring bones posed (their matrix_basis)."""
        arm = self.arm
        W = arm.matrix_world
        s = W.to_scale()[0]
        qW = W.to_quaternion()
        caps = self.capsules(thick)
        steps = max(1, min(4, math.ceil(dt / (1.0 / 60.0))))
        sdt = min(dt / steps, 1.0 / 30.0)
        settings = {}
        for _ in range(steps):
            computed = {}
            for j in self.joints:
                st = settings.get(j.root) or settings.setdefault(j.root, self.settings(j.root))
                parent = arm.data.bones[j.name].parent
                parent_M = self._posed(parent.name, computed) if parent else Matrix.Identity(4)
                M = parent_M @ j.rel_rest
                head = W @ M.translation
                rest_dir = (W.to_3x3() @ (M.to_3x3() @ j.axis)).normalized()
                length = j.length * s
                drag = max(0.0, min(1.0, st["drag"]))
                inertia = (j.tail - j.prev_tail) * (1.0 - drag)
                nxt = j.tail + inertia + rest_dir * st["stiffness"] * sdt + Vector((0, 0, -1)) * st["gravity"] * sdt
                d = nxt - head
                nxt = head + (d.normalized() if d.length > 1e-9 else rest_dir) * length
                for a, b, r in caps:
                    c = _closest_on_segment(nxt, a, b)
                    away = nxt - c
                    lim = r + st["radius"] * s
                    if away.length_squared < lim * lim:
                        nxt = c + (away.normalized() if away.length > 1e-9 else Vector((0, 1, 0))) * lim
                        d = nxt - head
                        nxt = head + (d.normalized() if d.length > 1e-9 else rest_dir) * length
                j.prev_tail = j.tail
                j.tail = nxt
                # Turned from its rest direction to the tail's (armature space)
                to = (nxt - head)
                to = to.normalized() if to.length > 1e-9 else rest_dir
                turn = qW.inverted() @ rest_dir.rotation_difference(to) @ qW
                h = M.translation
                new_M = Matrix.Translation(h) @ turn.to_matrix().to_4x4() @ Matrix.Translation(-h) @ M
                computed[j.name] = new_M
                j.basis = M.inverted() @ new_M
        for j in self.joints:
            arm.pose.bones[j.name].matrix_basis = j.basis

    def sway(self, t):
        """The hips turned back and forth about the armature's up (a hands-free test)."""
        pb = self.arm.pose.bones.get("Hips")
        if pb is None:
            return
        rest = pb.bone.matrix_local @ self.saved["Hips"]
        h = rest.translation
        a = math.radians(35.0) * math.sin(2.0 * math.pi * 0.6 * t)
        turned = Matrix.Translation(h) @ Matrix.Rotation(a, 4, "Z") @ Matrix.Translation(-h) @ rest
        pb.matrix_basis = pb.bone.matrix_local.inverted() @ turned

    def stop(self):
        for name, basis in self.saved.items():
            pb = self.arm.pose.bones.get(name)
            if pb is not None:
                pb.matrix_basis = basis


# ---------------------------------------------------------------------------
# Running it: a timer (about 60 a second) while it's on, and the colliders drawn

PREVIEW = None
_DRAW = None


def running():
    return PREVIEW is not None


def _tick():
    global PREVIEW
    p = PREVIEW
    if p is None:
        return None
    try:
        st = bpy.context.scene.theater_rig
        now = time.perf_counter()
        dt = min(now - p.last, 0.1)
        p.last = now
        if st.spring_sway:
            p.sway(now - p.started)
        p.step(dt, st.spring_colliders_thick)
    except (ReferenceError, KeyError, AttributeError) as e:
        # The armature went (undo, a new file): stop without putting back
        print("Theater Rig spring preview stopped:", e)
        PREVIEW = None
        _remove_draw()
        return None
    return 1.0 / 60.0


def _draw():
    p = PREVIEW
    try:
        if p is None or not bpy.context.scene.theater_rig.spring_show_colliders:
            return
        thick = bpy.context.scene.theater_rig.spring_colliders_thick
        coords = []
        for a, b, r in p.capsules(thick):
            coords += [a, b]
            axis = (b - a).normalized() if (b - a).length > 1e-6 else Vector((0, 0, 1))
            u = axis.orthogonal().normalized()
            v = axis.cross(u).normalized()
            for c in (a, b):
                for plane in ((u, v), (axis, u), (axis, v)):
                    pts = [c + (plane[0] * math.cos(k * math.pi / 8) + plane[1] * math.sin(k * math.pi / 8)) * r for k in range(17)]
                    for k in range(16):
                        coords += [pts[k], pts[k + 1]]
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "LINES", {"pos": [tuple(c) for c in coords]})
        shader.uniform_float("color", (1.0, 0.55, 0.1, 0.9))
        batch.draw(shader)
    except ReferenceError:
        pass


def _remove_draw():
    global _DRAW
    if _DRAW is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_DRAW, "WINDOW")
        _DRAW = None


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def start(arm):
    global PREVIEW, _DRAW
    stop()
    PREVIEW = Preview(arm)
    bpy.app.timers.register(_tick, first_interval=0.0)
    if _DRAW is None and not bpy.app.background:
        _DRAW = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    return PREVIEW


def stop():
    global PREVIEW
    p = PREVIEW
    PREVIEW = None
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _remove_draw()
    if p is not None:
        try:
            p.stop()
        except ReferenceError:
            pass
        if not bpy.app.background:
            _redraw()


@bpy.app.handlers.persistent
def _on_load(_):
    """A file opened: its preview is gone (nothing to put back)."""
    global PREVIEW
    PREVIEW = None
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _remove_draw()
