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
import math
import os

import bpy

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


def stored(arm):
    """The tiles on the armature now."""
    try:
        return json.loads(arm.get(PROP, "{}"))
    except (TypeError, ValueError):
        return {}


def store(arm):
    """Copies the VRM's tiles onto the armature (kept by Export), with the ones
    there already (made with Make Tiles; a VRM expression of the same name
    wins). Returns how many tiles it has."""
    tiles = stored(arm)
    tiles.update(collect(arm))
    if tiles:
        arm[PROP] = json.dumps(tiles)
    return len(tiles)


# ---------------------------------------------------------------------------
# Make Tiles: a texture that's a grid of pictures (eyes, mouths, faces), each
# cell a named tile. Two kinds of sheet:
# - the mesh's UVs already on one cell (VRoid's eyes): a tile moves them to
#   another cell (same size), and no tile shows the mesh's own cell;
# - the mesh's UVs over the whole sheet: a tile shrinks them to one cell, and
#   the material gets a Mapping node showing the default cell (exported as
#   the texture's KHR_texture_transform), or the whole sheet would show.

EPS = 1e-4


def materials_using(image):
    """The materials whose base colour is `image`."""
    from . import colour
    return [m for m in bpy.data.materials if colour.base_image(m) == image]


def _mapping(mat):
    """The Mapping node feeding the base colour texture, if any."""
    from . import colour
    tex, _ = colour._base_link(mat)
    if tex is None or not tex.inputs["Vector"].links:
        return None
    node = tex.inputs["Vector"].links[0].from_node
    return node if node.type == "MAPPING" else None


def base_transform(mat):
    """The material's texture placement in glTF's terms ([sx, sy, ox, oy]: uv'
    = uv * s + o, v down): its Mapping node's, else none."""
    node = _mapping(mat)
    if node is None or node.vector_type != "POINT":
        return [1.0, 1.0, 0.0, 0.0]
    loc, scale = node.inputs["Location"].default_value, node.inputs["Scale"].default_value
    return [scale[0], scale[1], loc[0], 1.0 - loc[1] - scale[1]]


def set_base_transform(mat, st):
    """Gives the material's base colour texture placement `st` (glTF's terms)
    through a Mapping node (made if it has none)."""
    from . import colour
    tex, _ = colour._base_link(mat)
    if tex is None:
        return False
    node = _mapping(mat)
    if node is None:
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        node = nodes.new("ShaderNodeMapping")
        node.vector_type = "POINT"
        node.location = (tex.location.x - 220, tex.location.y)
        uv = nodes.new("ShaderNodeUVMap")
        uv.location = (node.location.x - 200, node.location.y)
        links.new(uv.outputs["UV"], node.inputs["Vector"])
        links.new(node.outputs["Vector"], tex.inputs["Vector"])
    node.vector_type = "POINT"
    sx, sy, ox, oy = st
    node.inputs["Location"].default_value = (ox, 1.0 - oy - sy, 0.0)
    node.inputs["Scale"].default_value = (sx, sy, 1.0)
    node.inputs["Rotation"].default_value = (0.0, 0.0, 0.0)
    return True


def uv_bounds(materials):
    """The UVs of the faces using `materials` (glTF's v down), as
    (u min, u max, v min, v max); None when no face uses them."""
    names = {m.name for m in materials}
    lo_u = lo_v = float("inf")
    hi_u = hi_v = float("-inf")
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data.uv_layers:
            continue
        slots = [i for i, s in enumerate(obj.material_slots) if s.material and s.material.name in names]
        if not slots:
            continue
        uvs = obj.data.uv_layers.active.data
        for poly in obj.data.polygons:
            if poly.material_index not in slots:
                continue
            for li in poly.loop_indices:
                u, v = uvs[li].uv
                v = 1.0 - v
                lo_u, hi_u, lo_v, hi_v = min(lo_u, u), max(hi_u, u), min(lo_v, v), max(hi_v, v)
    return None if lo_u == float("inf") else (lo_u, hi_u, lo_v, hi_v)


def own_cell(bounds, st, columns, rows):
    """The cell (column, row) the UVs placed by `st` all sit in, or None when
    they cover more than one."""
    if bounds is None:
        return None
    lo_u, hi_u, lo_v, hi_v = bounds
    u0, u1 = lo_u * st[0] + st[2], hi_u * st[0] + st[2]
    v0, v1 = lo_v * st[1] + st[3], hi_v * st[1] + st[3]
    c0, c1 = math.floor(u0 * columns + EPS), math.floor(u1 * columns - EPS)
    r0, r1 = math.floor(v0 * rows + EPS), math.floor(v1 * rows - EPS)
    if c0 != c1 or r0 != r1:
        return None
    return c0 % columns, r0 % rows


def tile_names(text, image, count):
    """The tiles' names: the comma-separated `text`, across then down; one
    left blank (or missing) is <texture>_<cell>."""
    given = [n.strip() for n in text.split(",")] if text.strip() else []
    stem = os.path.splitext(image.name)[0]
    return [given[i] if i < len(given) and given[i] else f"{stem}_{i}" for i in range(count)]


def make(arm, image, columns, rows, names, default_cell=0):
    """Splits `image` into `columns` x `rows` tiles named `names` (comma
    separated, across then down), on every material using it, stored on
    `arm`. Tiles made before on those materials go. Returns (how many tiles,
    each material's kind: "cell" or "sheet")."""
    columns, rows = max(1, int(columns)), max(1, int(rows))
    count = columns * rows
    materials = materials_using(image)
    if not materials:
        raise ValueError(f"No material uses {image.name} as its base colour")
    labels = tile_names(names, image, count)
    tiles = {n: b for n, b in stored(arm).items() if not all(x["material"] in {m.name for m in materials} for x in b)}
    kinds = {}
    binds = [[] for _ in range(count)]
    for mat in materials:
        st = base_transform(mat)
        here = own_cell(uv_bounds([mat]), st, columns, rows)
        for cell in range(count):
            col, row = cell % columns, cell // columns
            if here is not None:
                # Same size, moved from its own cell to this one
                scale = [st[0], st[1]]
                offset = [st[2] + (col - here[0]) / columns, st[3] + (row - here[1]) / rows]
            else:
                scale = [1.0 / columns, 1.0 / rows]
                offset = [col / columns, row / rows]
            binds[cell].append({"material": mat.name, "scale": scale, "offset": offset})
        if here is None:
            d = default_cell % count
            set_base_transform(mat, [1.0 / columns, 1.0 / rows, (d % columns) / columns, (d // columns) / rows])
        kinds[mat.name] = "cell" if here is not None else "sheet"
    for name, b in zip(labels, binds):
        tiles[name] = b
    arm[PROP] = json.dumps(tiles)
    return count, kinds
