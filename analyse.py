"""Analyse: what an avatar has and what it lacks against the convention.
Reads only; changes nothing."""

from dataclasses import dataclass, field

import bpy

from . import conventions as cv


@dataclass
class BoneRole:
    role: str          # VRM role key (leftupperarm)
    bone: str          # the bone's name now
    target: str        # its Mixamo name
    source: str        # "vrm" or "name"


@dataclass
class SpringChain:
    kind: str
    roots: list
    bones: int
    target: str        # spring_<kind>_<n>
    settings: dict = field(default_factory=dict)
    source: str = "vrm"


@dataclass
class Expression:
    arkit: str
    status: str        # "present", "exact", "approximate", "missing"
    source: str = ""   # the shape key it comes from


@dataclass
class Report:
    armature: str = ""
    vrm_spec: str = ""
    roles: list = field(default_factory=list)
    missing_roles: list = field(default_factory=list)
    springs: list = field(default_factory=list)
    colliders: int = 0
    expressions: list = field(default_factory=list)
    face_mesh: str = ""
    mtoon_materials: list = field(default_factory=list)
    outline_modifiers: list = field(default_factory=list)
    color_groups: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def counts(self):
        by = lambda s: sum(1 for e in self.expressions if e.status == s)
        return {
            "roles": len(self.roles),
            "missing_roles": len(self.missing_roles),
            "springs": len(self.springs),
            "arkit_present": by("present"),
            "arkit_exact": by("exact"),
            "arkit_approximate": by("approximate"),
            "arkit_missing": by("missing"),
            "mtoon": len(self.mtoon_materials),
            "outlines": len(self.outline_modifiers),
            "color_slots": len(self.color_groups),
        }


def find_armature(context=None):
    obj = getattr(context, "active_object", None) if context else None
    if obj and obj.type == "ARMATURE":
        return obj
    if obj and obj.parent and obj.parent.type == "ARMATURE":
        return obj.parent
    return next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)


def _vrm_ext(arm):
    return getattr(arm.data, "vrm_addon_extension", None)


def _roles_from_vrm(ext):
    """{role key: bone name} from the VRM add-on's humanoid data."""
    out = {}
    if ext is None:
        return out
    if getattr(ext, "spec_version", "") == "1.0":
        bones = ext.vrm1.humanoid.human_bones
        for prop in bones.bl_rna.properties:
            item = getattr(bones, prop.identifier, None)
            node = getattr(item, "node", None)
            name = getattr(node, "bone_name", "") if node else ""
            if name:
                out[cv.role_key(prop.identifier)] = name
    else:
        # VRM 0.x thumbs are proximal/intermediate/distal; VRM 1.0's (which the
        # table follows) are metacarpal/proximal/distal
        thumb = {"thumbproximal": "thumbmetacarpal", "thumbintermediate": "thumbproximal"}
        for b in ext.vrm0.humanoid.human_bones:
            if b.node.bone_name:
                key = cv.role_key(b.bone)
                for old, new in thumb.items():
                    if key.endswith(old):
                        key = key[: -len(old)] + new
                out[key] = b.node.bone_name
    return out


def _roles_from_names(arm):
    """Roles guessed from common bone names, for a plain GLB."""
    guesses = {}
    lowered = {b.name.lower().replace("mixamorig:", "").replace("_", "").replace(".", ""): b.name for b in arm.data.bones}
    mixamo_by_lower = {v.lower(): k for k, v in cv.MIXAMO.items()}
    for low, name in lowered.items():
        role = mixamo_by_lower.get(low)
        if role and role not in guesses:
            guesses[role] = name
            continue
        # VRoid style: jbipcleftupperarm / jbiplupperarm
        stripped = low.replace("jbipc", "").replace("jbip", "")
        for side_tag, side in (("l", "left"), ("r", "right")):
            if stripped.startswith(side_tag):
                cand = side + stripped[1:]
                if cand in cv.MIXAMO and cand not in guesses:
                    guesses[cand] = name
        if stripped in cv.MIXAMO and stripped not in guesses:
            guesses[stripped] = name
    return guesses


def _springs(arm, ext, role_bones):
    chains = []
    colliders = 0
    if ext is not None and getattr(ext, "spec_version", "") == "1.0":
        sb = ext.spring_bone1
        colliders = len(sb.colliders)
        for s in sb.springs:
            joints = [j.node.bone_name for j in s.joints if j.node.bone_name]
            if joints:
                chains.append(SpringChain(cv.spring_kind(s.vrm_name, *joints), joints[:1], len(joints), ""))
    elif ext is not None:
        sa = ext.vrm0.secondary_animation
        colliders = len(sa.collider_groups)
        for g in sa.bone_groups:
            roots = [b.bone_name for b in g.bones if b.bone_name]
            if not roots:
                continue
            size = sum(_chain_length(arm, r) for r in roots)
            settings = {"stiffness": round(g.stiffiness, 3), "gravity": round(g.gravity_power, 3),
                        "drag": round(g.drag_force, 3), "radius": round(g.hit_radius, 3)}
            chains.append(SpringChain(cv.spring_kind(g.comment, *roots), roots, size, "", settings))
    if not chains:
        chains = _springs_from_names(arm, role_bones)
    # Names: spring_<kind>_<n>, numbered per kind
    per_kind = {}
    for c in chains:
        per_kind[c.kind] = per_kind.get(c.kind, 0) + 1
        c.target = f"spring_{c.kind}_{per_kind[c.kind]}"
    return chains, colliders


def _chain_length(arm, root):
    bone = arm.data.bones.get(root)
    n = 0
    while bone:
        n += 1
        bone = bone.children[0] if len(bone.children) == 1 else None
    return n


def _springs_from_names(arm, role_bones):
    """Plain GLB: chains of non-humanoid bones hanging off the skeleton whose
    names say what they are (hair, skirt, tail...). Chains already named by
    the convention (spring_<kind>_<n>_0 roots) come first, with their settings."""
    import re

    named = re.compile(r"^spring_([a-z]+)_(\d+)_0$")
    chains = []
    for bone in arm.data.bones:
        m = named.match(bone.name)
        if m:
            settings = {k: round(float(bone[f"spring_{k}"]), 3) for k in ("stiffness", "gravity", "drag", "radius")
                        if f"spring_{k}" in bone.keys()}
            size = sum(1 for b in arm.data.bones if b.name.startswith(f"spring_{m.group(1)}_{m.group(2)}_"))
            chains.append(SpringChain(m.group(1), [bone.name], size, "", settings, source="name"))
    if chains:
        return chains
    humanoid = set(role_bones)
    for bone in arm.data.bones:
        if bone.name in humanoid or bone.parent is None:
            continue
        if bone.parent.name not in humanoid:
            continue
        kind = cv.spring_kind(bone.name)
        if kind == "misc" or not bone.children:
            continue
        chains.append(SpringChain(kind, [bone.name], _chain_length(arm, bone.name), "", source="name"))
    return chains


def _face_mesh(arm):
    """The deformed mesh whose shape keys look most like expressions (ARKit or
    VRoid names), so props with many baked frames don't win."""
    known = set(cv.ARKIT) | {src for src, _ in cv.VROID_TO_ARKIT.values()}
    best, score = None, (0, 0)
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.data.shape_keys:
            continue
        deformed = o.parent == arm or any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)
        if not deformed:
            continue
        names = [k.name for k in o.data.shape_keys.key_blocks]
        s = (sum(1 for n in names if n in known), sum(1 for n in names if n.startswith(("Fcl_", "eye", "mouth", "brow", "jaw"))))
        if s > score:
            best, score = o, s
    return best


def _expressions(face):
    keys = {k.name for k in face.data.shape_keys.key_blocks} if face else set()
    out = []
    for name in cv.ARKIT:
        if name in keys:
            out.append(Expression(name, "present", name))
            continue
        src = cv.VROID_TO_ARKIT.get(name)
        if src and src[0] in keys:
            out.append(Expression(name, src[1], src[0]))
        else:
            out.append(Expression(name, "missing"))
    return out


def _materials():
    mtoon = []
    for m in bpy.data.materials:
        ext = getattr(m, "vrm_addon_extension", None)
        enabled = getattr(getattr(ext, "mtoon1", None), "enabled", False) if ext else False
        if enabled or "mtoon" in m.name.lower():
            mtoon.append(m.name)
    return mtoon


def _outlines():
    out = []
    for o in bpy.data.objects:
        for mod in getattr(o, "modifiers", []):
            group = getattr(mod, "node_group", None)
            label = f"{mod.name} {group.name if group else ''}".lower()
            if mod.type == "NODES" and ("outline" in label or "mtoon" in label):
                out.append(f"{o.name}: {mod.name}")
    return out


def _color_groups():
    groups = {}
    sources = [("material", m.name) for m in bpy.data.materials]
    sources += [("object", o.name) for o in bpy.data.objects]
    for kind, name in sources:
        slot = cv.color_slot(name)
        if slot is not None:
            groups.setdefault(slot, []).append(f"{kind}: {name}")
    return groups


def analyse(context=None):
    rep = Report()
    arm = find_armature(context)
    if arm is None:
        rep.notes.append("No armature in the scene.")
        return rep
    rep.armature = arm.name
    ext = _vrm_ext(arm)
    rep.vrm_spec = getattr(ext, "spec_version", "") if ext else ""
    if rep.vrm_spec not in ("0.0", "1.0"):
        rep.vrm_spec = ""
        ext = None

    roles = _roles_from_vrm(ext)
    source = "vrm"
    if not roles:
        # No humanoid mapping: not (or no longer) a VRM, whatever empty data the add-on left
        rep.vrm_spec, ext = "", None
        roles, source = _roles_from_names(arm), "name"
    for role, bone in sorted(roles.items()):
        target = cv.MIXAMO.get(role)
        if target:
            rep.roles.append(BoneRole(role, bone, target, source))
    rep.missing_roles = [r for r in cv.REQUIRED_ROLES if r not in roles]

    rep.springs, rep.colliders = _springs(arm, ext, roles.values())

    face = _face_mesh(arm)
    rep.face_mesh = face.name if face else ""
    rep.expressions = _expressions(face)
    if face is None:
        rep.notes.append("No mesh with shape keys found for expressions.")

    rep.mtoon_materials = _materials()
    rep.outline_modifiers = _outlines()
    rep.color_groups = _color_groups()
    return rep


def as_text(rep):
    c = rep.counts()
    lines = [
        f"Armature: {rep.armature}   VRM: {rep.vrm_spec or 'none (plain GLB)'}",
        f"Bone roles: {c['roles']} found, {c['missing_roles']} required missing {rep.missing_roles or ''}",
    ]
    for r in rep.roles:
        lines.append(f"  {r.bone:32} -> {r.target:22} ({r.role}, from {r.source})")
    lines.append(f"Spring chains: {c['springs']}   collider groups: {rep.colliders}")
    for s in rep.springs:
        lines.append(f"  {s.target:22} {len(s.roots)} root(s), {s.bones} bones  {s.roots[:3]} {s.settings}")
    lines.append(f"Expressions on '{rep.face_mesh}': {c['arkit_present']} ARKit already, "
                 f"{c['arkit_exact']} exact, {c['arkit_approximate']} approximate, {c['arkit_missing']} missing")
    for e in rep.expressions:
        if e.status != "missing":
            lines.append(f"  {e.arkit:20} {e.status:12} <- {e.source}")
    lines.append("  missing: " + ", ".join(e.arkit for e in rep.expressions if e.status == "missing"))
    lines.append(f"MToon materials: {c['mtoon']}   outline modifiers: {c['outlines']}")
    for o in rep.outline_modifiers:
        lines.append(f"  outline {o}")
    lines.append(f"Colour slots: {sorted(rep.color_groups) or 'none'}")
    for slot, items in sorted(rep.color_groups.items()):
        lines.append(f"  Color{slot}: {items}")
    lines += [f"Note: {n}" for n in rep.notes]
    return "\n".join(lines)
