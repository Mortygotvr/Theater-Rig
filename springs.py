"""Rename Springs: every spring chain's bones become spring_<kind>_<n>_<i>,
and the chain's settings go on its root bone as custom properties (exported to
the GLB as node extras), so the renderer finds both without the VRM data."""

import bpy

from . import analyse as an
from . import rename

SETTINGS = ("stiffness", "gravity", "drag", "radius")


def _descendants(bone):
    """The bone and everything under it, depth first (branches included)."""
    out = [bone]
    for child in bone.children:
        out += _descendants(child)
    return out


def plan(arm, chains):
    """[(chain name, root bone, [(old, new)], settings)]: one chain per VRM root,
    numbered per kind (a VRM group with two roots, like the bust, gives two)."""
    bones = arm.data.bones
    per_kind, out, taken = {}, [], set()
    for chain in chains:
        for root in chain.roots:
            bone = bones.get(root)
            if bone is None or root in taken:
                continue
            per_kind[chain.kind] = per_kind.get(chain.kind, 0) + 1
            name = f"spring_{chain.kind}_{per_kind[chain.kind]}"
            members = [b for b in _descendants(bone) if b.name not in taken]
            taken.update(b.name for b in members)
            mapping = [(b.name, f"{name}_{i}") for i, b in enumerate(members)]
            out.append((name, mapping[0][1], mapping, dict(chain.settings)))
    return out


def rename_springs(context=None):
    arm = an.find_armature(context)
    if arm is None:
        return None, []
    rep = an.analyse(context)
    chains = plan(arm, rep.springs)
    mapping = [pair for _, _, pairs, _ in chains for pair in pairs]
    rename.rename_bones_map(arm, mapping)
    for name, root, _, settings in chains:
        # On the armature's bone: that's where the glTF exporter reads extras
        bone = arm.data.bones.get(root)
        if bone is None:
            continue
        for key in SETTINGS:
            if key in settings:
                bone[f"spring_{key}"] = float(settings[key])
    return arm, chains
