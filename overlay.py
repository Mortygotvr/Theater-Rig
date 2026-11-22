"""Overlays: a picture on top of a material's texture (a logo, a tattoo,
painted clothes, a layer the artist kept apart), without touching that
texture. The faces using the material are copied, a hair's width out along
their normals, with a material of their own: the overlay PNG (painted on the
same UV layout, transparent where there's nothing), blended over what's
under. The copy keeps the faces' weights and shape keys, so it bends with
the body; being a material of its own, it takes colour slots, tiles, a
Show/Hide like any other. Every viewer shows it: it's plain geometry.

Each overlay is marked: its material has `theater_overlay` (the material it
lies on), so Remove Overlay finds its faces again."""

import os

import bmesh
import bpy

PROP = "theater_overlay"
# How far out the copy lies, metres (in the object's own size): enough not to
# flicker with the skin, too little to see
LIFT = 0.0002


def users(material):
    """The mesh objects whose faces use `material`."""
    return [o for o in bpy.data.objects if o.type == "MESH" and any(s.material == material for s in o.material_slots)]


def overlays():
    """Every overlay material, with the material it lies on."""
    return [(m, m[PROP]) for m in bpy.data.materials if PROP in m]


def over(material):
    """The overlays lying on `material`."""
    return [m for m, under in overlays() if under == material.name]


def _material(base, image, name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat[PROP] = base.name
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.location = (bsdf.location.x - 320, bsdf.location.y)
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    # As matte as the material under it (no shine of its own)
    bsdf.inputs["Roughness"].default_value = 1.0
    # Blended over what's under (the glTF export: alphaMode BLEND)
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    mat.use_backface_culling = base.use_backface_culling
    # It lies over the skin: a shadow of its own would double it
    if hasattr(mat, "use_transparent_shadow"):
        mat.use_transparent_shadow = True
    return mat


def add(base, image, name=None):
    """Lays `image` over `base`: its faces copied, lifted, with the overlay's
    material. Returns (the overlay material, how many faces)."""
    objs = users(base)
    if not objs:
        raise ValueError(f"No mesh uses {base.name}")
    stem = name or os.path.splitext(image.name)[0]
    mat = _material(base, image, f"{base.name} + {stem}")
    faces = 0
    for obj in objs:
        mesh = obj.data
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        base_index = next(i for i, s in enumerate(obj.material_slots) if s.material == base)
        obj.data.materials.append(mat)
        new_index = len(obj.material_slots) - 1
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.normal_update()
        src = [f for f in bm.faces if f.material_index == base_index]
        if not src:
            bm.free()
            continue
        # Each vertex lifted along its normal at rest, in every shape key too
        lift = {v: v.normal.copy() * LIFT for f in src for v in f.verts}
        dup = bmesh.ops.duplicate(bm, geom=src)
        vmap = dup["vert_map"]
        keys = list(bm.verts.layers.shape.values())
        for old, new in vmap.items():
            if not isinstance(old, bmesh.types.BMVert):
                continue
            d = lift.get(old)
            if d is None:
                continue
            new.co += d
            for layer in keys:
                new[layer] += d
        for f in dup["geom"]:
            if isinstance(f, bmesh.types.BMFace):
                f.material_index = new_index
                faces += 1
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
    return mat, faces


def remove(mat):
    """Takes overlay `mat` off: its faces, its slot, the material. Returns how many faces."""
    if PROP not in mat:
        raise ValueError(f"{mat.name} isn't an overlay")
    faces = 0
    for obj in users(mat):
        mesh = obj.data
        index = next(i for i, s in enumerate(obj.material_slots) if s.material == mat)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        gone = [f for f in bm.faces if f.material_index == index]
        faces += len(gone)
        loose = {v for f in gone for v in f.verts}
        bmesh.ops.delete(bm, geom=gone, context="FACES_ONLY")
        bmesh.ops.delete(bm, geom=[v for v in loose if v.is_valid and not v.link_faces], context="VERTS")
        # The slots after it move down one
        for f in bm.faces:
            if f.material_index > index:
                f.material_index -= 1
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.pop(index=index)
        mesh.update()
    bpy.data.materials.remove(mat)
    return faces
