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


def image_of_selection(context):
    """The base colour texture of the active object's active material."""
    obj = context.active_object
    mat = obj.active_material if obj else None
    return base_image(mat), mat


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
        mat[DEFAULT_PROP] = [float(c) for c in np.clip(factor * tint, 0.0, 1.0)]
        tex.image = grey
        if mix is not None:
            bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            mat.node_tree.nodes.remove(mix)
        mat.name = slot_name(mat.name, slot)
    return grey, users
