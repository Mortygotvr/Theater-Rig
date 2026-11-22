"""Tile textures: a texture that's a grid of pictures (eyes, mouths, faces in
one image), and named tiles that each show one of them. One standard for
every avatar, kept on the armature as `theater_tiles` (glTF extras):

    {"<tile>": {"set": "<set>", "order": n,
                "binds": [{"material": "<name>", "scale": [sx, sy], "offset": [ox, oy]}, ...]}, ...}

in glTF's texture coordinates (KHR_texture_transform's: v down, offset from
the top left): uv' = uv * scale + offset. A set is tiles that go together
("next" and "random" go through a set, in its order).

Test Tile shows a tile in Blender as Theater Puppet shows it (its binds on
the materials' texture placement); Back to Normal (and Export) puts the
materials back as they were.

Two ways to get them:
- Make Tiles: splits a texture into a grid of named tiles (a set);
- Convert VRM Tiles: the VRM expressions that move a texture (VRM 0.x:
  material values on _MainTex_ST; VRM 1.0: texture transform binds), as the
  set "expressions". Export does it too when it hasn't been done, before it
  removes the VRM data.
The old form (a tile's binds alone, no set) is read as the set "expressions"."""

import json
import math
import os

import bpy

PROP = "theater_tiles"


def _from_unity_st(st):
    """VRM 0.x's _MainTex_ST (Unity: v up) as glTF's (scale, offset)."""
    sx, sy, ox, oy = (list(st) + [1.0, 1.0, 0.0, 0.0][len(st):])[:4]
    return [sx, sy], [ox, 1.0 - sy - oy]


VRM_SET = "expressions"


def collect(arm):
    """Every expression's tile binds, from the VRM data on the armature
    ({expression: binds}, in the VRM's order)."""
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


def entry(set_name, order, binds):
    return {"set": set_name, "order": order, "binds": binds}


def normalised(data):
    """`theater_tiles` in the standard form (the old form: binds alone)."""
    out = {}
    for i, (name, v) in enumerate(sorted(data.items()) if isinstance(data, dict) else []):
        if isinstance(v, list):
            out[name] = entry(VRM_SET, i, v)
        elif isinstance(v, dict) and isinstance(v.get("binds"), list):
            out[name] = entry(str(v.get("set", "")), int(v.get("order", i)), v["binds"])
    return out


def stored(arm):
    """The tiles on the armature now (standard form)."""
    try:
        return normalised(json.loads(arm.get(PROP, "{}")))
    except (TypeError, ValueError):
        return {}


def save(arm, tiles):
    arm[PROP] = json.dumps(tiles)


def sets(arm):
    """{set: [tile names, in order]}."""
    out = {}
    for name, t in sorted(stored(arm).items(), key=lambda kv: (kv[1]["set"], kv[1]["order"], kv[0])):
        out.setdefault(t["set"], []).append(name)
    return out


def convert(arm):
    """The VRM's tile expressions as the set "expressions" (it replaces that
    set; the other sets stay). Returns how many."""
    found = collect(arm)
    if not found:
        return 0
    tiles = {n: t for n, t in stored(arm).items() if t["set"] != VRM_SET and n not in found}
    for i, (name, binds) in enumerate(found.items()):
        tiles[name] = entry(VRM_SET, i, binds)
    save(arm, tiles)
    return len(found)


def remove_set(arm, set_name):
    """Removes a set's tiles; returns how many."""
    before = stored(arm)
    kept = {n: t for n, t in before.items() if t["set"] != set_name}
    save(arm, kept)
    return len(before) - len(kept)


def store(arm):
    """Before Export: the VRM's tiles converted (when they haven't been yet),
    the tiles saved in the standard form. Returns how many tiles it has."""
    tiles = stored(arm)
    if not any(t["set"] == VRM_SET for t in tiles.values()) and collect(arm):
        convert(arm)
        tiles = stored(arm)
    if tiles:
        save(arm, tiles)
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


def set_base_transform(mat, st, label=""):
    """Gives the material's base colour texture placement `st` (glTF's terms)
    through a Mapping node (made if it has none, labelled `label`)."""
    from . import colour
    tex, _ = colour._base_link(mat)
    if tex is None:
        return False
    node = _mapping(mat)
    if node is None:
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        node = nodes.new("ShaderNodeMapping")
        node.label = label
        node.vector_type = "POINT"
        node.location = (tex.location.x - 220, tex.location.y)
        uv = nodes.new("ShaderNodeUVMap")
        uv.label = label
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


def set_name_of(image, set_name=""):
    """The set Make Tiles fills: the one given, else the texture's name."""
    return set_name.strip() or os.path.splitext(image.name)[0]


def make(arm, image, columns, rows, names, default_cell=0, set_name=""):
    """Splits `image` into `columns` x `rows` tiles named `names` (comma
    separated, across then down), on every material using it: the set
    `set_name` (else the texture's name), replacing it, stored on `arm`.
    Returns (how many tiles, each material's kind: "cell" or "sheet")."""
    columns, rows = max(1, int(columns)), max(1, int(rows))
    count = columns * rows
    materials = materials_using(image)
    if not materials:
        raise ValueError(f"No material uses {image.name} as its base colour")
    labels = tile_names(names, image, count)
    group = set_name_of(image, set_name)
    tiles = {n: t for n, t in stored(arm).items() if t["set"] != group and n not in labels}
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
    for i, (name, b) in enumerate(zip(labels, binds)):
        tiles[name] = entry(group, i, b)
    save(arm, tiles)
    return count, kinds


# ---------------------------------------------------------------------------
# Test Tile: a tile shown in Blender, as Theater Puppet shows it (its binds
# as the materials' texture placement), until Back to Normal. What each
# material had before is kept on the armature (`theater_tile_test`), so it
# comes back exactly: a material that had no Mapping node loses the one the
# test made (it would export the tile otherwise).

TEST = "theater_tile_test"
TEST_LABEL = "Theater tile test"


def _snapshot(mat):
    """The material's Mapping node exactly (its mode, location, rotation,
    scale), or None when it has none: what Back to Normal puts back."""
    node = _mapping(mat)
    if node is None:
        return None
    return {
        "type": node.vector_type,
        "location": list(node.inputs["Location"].default_value),
        "rotation": list(node.inputs["Rotation"].default_value),
        "scale": list(node.inputs["Scale"].default_value),
    }


def _put_back(mat, snap):
    """The Mapping node as `snap` had it."""
    node = _mapping(mat)
    if node is None:
        return
    node.vector_type = snap["type"]
    node.inputs["Location"].default_value = snap["location"]
    node.inputs["Rotation"].default_value = snap["rotation"]
    node.inputs["Scale"].default_value = snap["scale"]


def _test_state(arm):
    try:
        state = json.loads(arm.get(TEST, "{}"))
    except (TypeError, ValueError):
        state = {}
    return state if isinstance(state, dict) else {}


def tested(arm):
    """The tile being tested ("" when none)."""
    return str(_test_state(arm).get("tile", "")) if arm is not None else ""


def test(arm, name):
    """Shows tile `name` on its materials. Returns how many materials."""
    tile = stored(arm).get(name)
    if tile is None:
        raise ValueError(f"No tile named {name}")
    state = _test_state(arm)
    before = state.get("before", {})
    shown = 0
    for b in tile["binds"]:
        mat = bpy.data.materials.get(b.get("material", ""))
        if mat is None:
            continue
        if mat.name not in before:
            before[mat.name] = _snapshot(mat)
        scale, offset = b.get("scale", [1.0, 1.0]), b.get("offset", [0.0, 0.0])
        if set_base_transform(mat, [scale[0], scale[1], offset[0], offset[1]], TEST_LABEL):
            shown += 1
    arm[TEST] = json.dumps({"tile": name, "before": before})
    return shown


def step(arm, set_name, by):
    """Tests the tile `by` places on from the one tested in `set_name` (the
    set's first when none of its tiles is). Returns its name."""
    names = sets(arm).get(set_name, [])
    if not names:
        raise ValueError(f"No set named {set_name}")
    now = tested(arm)
    i = (names.index(now) + by) % len(names) if now in names else (0 if by >= 0 else len(names) - 1)
    test(arm, names[i])
    return names[i]


def restore(arm):
    """Back to Normal: every material the test changed as it was. Returns how many."""
    if arm is None or TEST not in arm:
        return 0
    from . import colour
    before = _test_state(arm).get("before", {})
    for mat_name, st in before.items():
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            continue
        if isinstance(st, dict):
            _put_back(mat, st)
            continue
        if st is not None:
            # (A test from before: kept as glTF's placement only)
            set_base_transform(mat, st)
            continue
        # It had no Mapping node: the test's go (the texture reads the UVs again)
        node = _mapping(mat)
        if node is not None and node.label == TEST_LABEL:
            nodes = mat.node_tree.nodes
            if node.inputs["Vector"].links:
                uv = node.inputs["Vector"].links[0].from_node
                if uv.type == "UVMAP" and uv.label == TEST_LABEL:
                    nodes.remove(uv)
            nodes.remove(node)
        tex, _ = colour._base_link(mat)
        if tex is not None:
            for link in list(tex.inputs["Vector"].links):
                mat.node_tree.links.remove(link)
    del arm[TEST]
    return len(before)


# Saving the .blend while a tile is tested: saved as normal (the test isn't
# part of the avatar), then the tile shown again
_resume = []


@bpy.app.handlers.persistent
def _save_pre(*_):
    _resume.clear()
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and TEST in obj:
            name = tested(obj)
            restore(obj)
            if name:
                _resume.append((obj.name, name))


@bpy.app.handlers.persistent
def _save_post(*_):
    for arm_name, tile in _resume:
        arm = bpy.data.objects.get(arm_name)
        if arm is not None and tile in stored(arm):
            test(arm, tile)
    _resume.clear()


def register_handlers():
    if _save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_save_pre)
    if _save_post not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_save_post)


def unregister_handlers():
    for handlers, fn in ((bpy.app.handlers.save_pre, _save_pre), (bpy.app.handlers.save_post, _save_post)):
        if fn in handlers:
            handlers.remove(fn)
