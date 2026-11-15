"""Detoonify: MToon materials become plain Principled BSDF materials that keep
their colours, and the MToon outlines go (a filter redraws them).

Kept: base colour (texture x lit colour), emission (texture x colour), normal
map, transparency (opaque / cut-out / blended), double-sidedness, and the
shade colour as the custom property `shade_color` (exported as glTF extras
for toon filters). Dropped: toony/shift, matcap, rim, outlines."""

import bpy

from . import conventions as cv

SHADE_PROP = "shade_color"


def _image(texture_info):
    idx = getattr(texture_info, "index", None)
    img = getattr(idx, "source", None) if idx else None
    # The VRM add-on's stand-in for "no texture"
    if img is None or img.name.startswith("Shader_None"):
        return None
    return img


def _is_white(c):
    return all(abs(v - 1.0) < 1e-4 for v in c[:3])


def _is_black(c):
    return all(abs(v) < 1e-4 for v in c[:3])


def _times(nodes, links, socket, color, loc):
    """socket x color, through a Multiply node (what the glTF exporter reads as a factor)."""
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.location = loc
    mix.inputs["Factor"].default_value = 1.0
    links.new(socket, mix.inputs["A"])
    mix.inputs["B"].default_value = (*color[:3], 1.0)
    return mix.outputs["Result"]


def read_mtoon(mat):
    """What's worth keeping from a MToon material, or None if it isn't one."""
    ext = getattr(mat, "vrm_addon_extension", None)
    mt = getattr(ext, "mtoon1", None) if ext else None
    if mt is None or not mt.enabled:
        return None
    pbr = mt.pbr_metallic_roughness
    x = mt.extensions.vrmc_materials_mtoon
    return {
        "base_color": tuple(pbr.base_color_factor),
        "base_image": _image(pbr.base_color_texture),
        "emissive": tuple(mt.emissive_factor),
        "emissive_image": _image(mt.emissive_texture),
        "normal_image": _image(mt.normal_texture),
        "normal_scale": getattr(mt.normal_texture, "scale", 1.0),
        "shade_color": tuple(x.shade_color_factor),
        "alpha_mode": mt.alpha_mode,
        "alpha_cutoff": mt.alpha_cutoff,
        "double_sided": mt.double_sided,
    }


def build_plain(mat, d):
    """Rebuild `mat` as a Principled BSDF with the colours in `d`."""
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Metallic"].default_value = 0.0

    base = d["base_color"]
    if d["base_image"]:
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = d["base_image"]
        tex.location = (-500, 200)
        color = tex.outputs["Color"]
        if not _is_white(base):
            color = _times(nodes, links, color, base, (-150, 250))
        links.new(color, bsdf.inputs["Base Color"])
        if d["alpha_mode"] != "OPAQUE":
            links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    else:
        bsdf.inputs["Base Color"].default_value = (*base[:3], 1.0)
        if d["alpha_mode"] != "OPAQUE":
            bsdf.inputs["Alpha"].default_value = base[3]

    emissive = d["emissive"]
    if not _is_black(emissive):
        if d["emissive_image"]:
            etex = nodes.new("ShaderNodeTexImage")
            etex.image = d["emissive_image"]
            etex.location = (-500, -250)
            ecolor = etex.outputs["Color"]
            if not _is_white(emissive):
                ecolor = _times(nodes, links, ecolor, emissive, (-150, -250))
            links.new(ecolor, bsdf.inputs["Emission Color"])
        else:
            bsdf.inputs["Emission Color"].default_value = (*emissive[:3], 1.0)
        bsdf.inputs["Emission Strength"].default_value = 1.0

    if d["normal_image"]:
        ntex = nodes.new("ShaderNodeTexImage")
        ntex.image = d["normal_image"]
        ntex.image.colorspace_settings.name = "Non-Color"
        ntex.location = (-500, -550)
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.location = (-150, -550)
        nmap.inputs["Strength"].default_value = d["normal_scale"]
        links.new(ntex.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])

    # Transparency: blended, or cut-out at the cutoff
    if d["alpha_mode"] == "BLEND":
        mat.surface_render_method = "BLENDED"
    else:
        mat.surface_render_method = "DITHERED"
    if d["alpha_mode"] == "MASK":
        alpha_in = bsdf.inputs["Alpha"]
        src = alpha_in.links[0].from_socket if alpha_in.links else None
        if src is not None:
            # The glTF exporter reads "alpha >= cutoff" (1 - (alpha < cutoff)) as MASK
            lt = nodes.new("ShaderNodeMath")
            lt.operation = "LESS_THAN"
            lt.location = (-150, 0)
            lt.inputs[1].default_value = d["alpha_cutoff"]
            inv = nodes.new("ShaderNodeMath")
            inv.operation = "SUBTRACT"
            inv.location = (50, 0)
            inv.inputs[0].default_value = 1.0
            links.new(src, lt.inputs[0])
            links.new(lt.outputs[0], inv.inputs[1])
            links.new(inv.outputs[0], alpha_in)
    mat.use_backface_culling = not d["double_sided"]

    mat[SHADE_PROP] = list(d["shade_color"][:3])


def is_outline_modifier(mod):
    group = getattr(mod, "node_group", None)
    label = f"{mod.name} {group.name if group else ''}".lower()
    return mod.type == "NODES" and ("outline" in label or "mtoon" in label)


def detoonify():
    """Converts every MToon material and removes MToon outlines. Returns
    (materials converted, outline modifiers removed)."""
    converted = 0
    for mat in list(bpy.data.materials):
        d = read_mtoon(mat)
        if d is None:
            continue
        # Off first: the VRM add-on stops managing the node tree
        mat.vrm_addon_extension.mtoon1.enabled = False
        build_plain(mat, d)
        converted += 1
    removed = 0
    groups = set()
    for obj in bpy.data.objects:
        for mod in list(getattr(obj, "modifiers", [])):
            if is_outline_modifier(mod):
                if mod.node_group:
                    groups.add(mod.node_group)
                obj.modifiers.remove(mod)
                removed += 1
    # The outline node groups and their materials, now used by nothing
    for group in groups:
        if group.users == 0:
            bpy.data.node_groups.remove(group)
    for mat in list(bpy.data.materials):
        if mat.name.startswith("MToon Outline"):
            bpy.data.materials.remove(mat)
    return converted, removed
