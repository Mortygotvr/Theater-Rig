"""Tile textures: VRM expressions that move a material's texture (a grid of
eyes, mouths, faces in one image) to show another tile. VRM keeps them in its
expressions (VRM 0.x: material values on _MainTex_ST; VRM 1.0: texture
transform binds), which Export removes with the rest of the VRM data, so
Export first copies them onto the armature as `theater_tiles` (glTF extras),
for the renderer:

    {"<expression>": [{"material": "<name>", "scale": [sx, sy], "offset": [ox, oy]}, ...], ...}

in glTF's texture coordinates (KHR_texture_transform's: v down, offset from
the top left): uv' = uv * scale + offset."""

import json

PROP = "theater_tiles"


def _from_unity_st(st):
    """VRM 0.x's _MainTex_ST (Unity: v up) as glTF's (scale, offset)."""
    sx, sy, ox, oy = (list(st) + [1.0, 1.0, 0.0, 0.0][len(st):])[:4]
    return [sx, sy], [ox, 1.0 - sy - oy]


def collect(arm):
    """Every expression's tile binds, from the VRM data on the armature."""
    ext = getattr(arm.data, "vrm_addon_extension", None)
    if ext is None:
        return {}
    out = {}
    vrm1 = ext.is_vrm1() if hasattr(ext, "is_vrm1") else False
    if not vrm1:
        for group in ext.vrm0.blend_shape_master.blend_shape_groups:
            binds = []
            for mv in group.material_values:
                if mv.material is None or mv.property_name != "_MainTex_ST":
                    continue
                scale, offset = _from_unity_st([v.value for v in mv.target_value])
                binds.append({"material": mv.material.name, "scale": scale, "offset": offset})
            if binds and group.name:
                out[group.name] = binds
    else:
        for name, expression in ext.vrm1.expressions.all_name_to_expression_dict().items():
            binds = [
                {"material": b.material.name, "scale": list(b.scale), "offset": list(b.offset)}
                for b in expression.texture_transform_binds
                if b.material is not None
            ]
            if binds:
                out[name] = binds
    return out


def store(arm):
    """Copies the tiles onto the armature (kept by Export). Returns how many
    expressions have some; an avatar without VRM data keeps what it has."""
    tiles = collect(arm)
    if tiles:
        arm[PROP] = json.dumps(tiles)
    return len(tiles) if tiles else len(json.loads(arm.get(PROP, "{}")))
