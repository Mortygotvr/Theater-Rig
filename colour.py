"""Colour slots: a texture becomes greyscale and follows colour slot N.

The grey copy is each pixel's brightest channel, and the material goes plain
grey (no colour factor): the renderer multiplies it by slot N's colour. The
colour it had is kept as the material property `color_default` (glTF extras),
a starting colour for the slot. The copy, and every material using the
texture, gets Color<N> in its name. The original image is kept, unused."""

import re

import bpy
import numpy as np

from . import conventions as cv

DEFAULT_PROP = "color_default"

def _base_link(mat):
    """(image node, multiply node or None) feeding the Principled Base Color."""
    if not mat or not mat.use_nodes:
        return None, None
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None or not bsdf.inputs["Base Color"].links:
        return None, None
    node = bsdf.inputs["Base Color"].links[0].from_node
    if node.type == "TEX_IMAGE":
        return node, None
    if node.type == "MIX" and node.blend_type == "MULTIPLY" and node.inputs["A"].links:
        src = node.inputs["A"].links[0].from_node
        if src.type == "TEX_IMAGE":
            return src, node
    return None, None


def base_image(mat):
    tex, _ = _base_link(mat)
    return tex.image if tex else None


def images_of_selection(context):
    """The base colour textures the selection shows: [(image, [material names],
    faces)], most faces first. In Edit Mode, those of the selected faces (a
    body is one object with skin, hair, clothes… as materials: its active slot
    says nothing of the part wanted); else every material of the selected
    objects (faces: 0)."""
    import bmesh
    found = {}

    def add(img, mat, faces):
        names, n = found.get(img, ([], 0))
        if mat.name not in names:
            names.append(mat.name)
        found[img] = (names, n + faces)

    if context.mode == "EDIT_MESH":
        for obj in context.objects_in_mode or [context.active_object]:
            if obj is None or obj.type != "MESH":
                continue
            counts = {}
            for f in bmesh.from_edit_mesh(obj.data).faces:
                if f.select:
                    counts[f.material_index] = counts.get(f.material_index, 0) + 1
            for i, n in counts.items():
                mat = obj.material_slots[i].material if i < len(obj.material_slots) else None
                img = base_image(mat)
                if img is not None:
                    add(img, mat, n)
    else:
        objs = [o for o in context.selected_objects if o.type == "MESH"]
        if context.active_object in objs:
            objs.remove(context.active_object)
            objs.insert(0, context.active_object)
        # The active slot's first (a script asking without a list gets it)
        active = context.active_object.active_material if context.active_object in objs else None
        if base_image(active) is not None:
            add(base_image(active), active, 0)
        for obj in objs:
            for s in obj.material_slots:
                img = base_image(s.material)
                if img is not None:
                    add(img, s.material, 0)
    out = [(img, names, n) for img, (names, n) in found.items()]
    out.sort(key=lambda x: -x[2])   # stable: same faces keep their order
    return out


def slot_name(name, slot):
    """name with Color<slot> in it (an existing Color<M> is replaced)."""
    if cv.COLOR_GROUP.search(name):
        return cv.COLOR_GROUP.sub(f"Color{slot}", name, count=1)
    stem, dot, ext = name.rpartition(".") if re.search(r"\.(png|jpe?g|tga|bmp)$", name, re.I) else (name, "", "")
    return f"{stem}_Color{slot}{dot}{ext}"


def _greyscale(img):
    """(grey pixels RGBA flat, the tint that times the grey gives back the original)."""
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    rgb, alpha = px[:, :3], px[:, 3]
    # The brightest channel (HSV value): the grey keeps the shading, the tint
    # keeps the hue at full strength and never needs to go over 1
    grey = rgb.max(axis=1)
    seen = alpha > 0.5          # atlas gaps don't count
    if not seen.any():
        seen = np.ones_like(alpha, dtype=bool)
    tint = rgb[seen].mean(axis=0) / max(float(grey[seen].mean()), 1e-4)
    out = np.empty_like(px)
    out[:, 0] = out[:, 1] = out[:, 2] = grey
    out[:, 3] = alpha
    return out.ravel(), np.clip(tint, 0.0, 1.0)


def _mtoon(mat):
    """The VRM add-on's MToon data of `mat`, when it's on."""
    ext = getattr(mat, "vrm_addon_extension", None)
    mt = getattr(ext, "mtoon1", None) if ext else None
    return mt if mt is not None and getattr(mt, "enabled", False) else None


def _source(texture_info):
    idx = getattr(texture_info, "index", None)
    return getattr(idx, "source", None) if idx else None


def make_color_slot(image, slot):
    """Greyscale `image` into colour slot `slot`. Returns (grey image, [materials])."""
    users = [m for m in bpy.data.materials if base_image(m) == image]
    pixels, tint = _greyscale(image)
    w, h = image.size
    grey = bpy.data.images.new(slot_name(image.name, slot), w, h, alpha=True)
    grey.colorspace_settings.name = image.colorspace_settings.name
    grey.alpha_mode = image.alpha_mode
    grey.pixels.foreach_set(pixels)
    grey.pack()

    for mat in users:
        tex, mix = _base_link(mat)
        # The colour it showed (its factor on top of the texture's) is kept as a
        # property only; the material itself goes plain grey
        factor = np.array(mix.inputs["B"].default_value[:3]) if mix else np.ones(3)
        # A MToon material (not detoonified yet): its VRM data names the
        # texture and the factor too, and Detoonify / a VRM export rebuild from
        # them. They take the grey copy and white, or the old texture comes back
        mt = _mtoon(mat)
        if mt is not None:
            pbr = mt.pbr_metallic_roughness
            if _source(pbr.base_color_texture) == image:
                pbr.base_color_texture.index.source = grey
                if mix is None:
                    factor = np.array(pbr.base_color_factor[:3])
                pbr.base_color_factor = (1.0, 1.0, 1.0, pbr.base_color_factor[3])
            shade = getattr(mt.extensions.vrmc_materials_mtoon, "shade_multiply_texture", None)
            if shade is not None and _source(shade) == image:
                shade.index.source = grey
        mat[DEFAULT_PROP] = [float(c) for c in np.clip(factor * tint, 0.0, 1.0)]
        tex.image = grey
        if mix is not None:
            bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            mat.node_tree.nodes.remove(mix)
        mat.name = slot_name(mat.name, slot)
    return grey, users
