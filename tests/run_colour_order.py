"""Headless test: Make Colour Slot before or after Detoonify, then Export: the
slot's material keeps the grey texture (Detoonify rebuilds MToon materials
from their VRM data, which used to name the old texture).

blender --background --python tests/run_colour_order.py -- <model.vrm> <out.glb> slot-first|detoon-first"""
import importlib.util, io, json, os, struct, sys
import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src, out, order = sys.argv[sys.argv.index("--") + 1:]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec); sys.modules["theater_rig"] = rig; spec.loader.exec_module(rig); rig.register()
col = sys.modules["theater_rig.colour"]; detoon = sys.modules["theater_rig.detoon"]; export = sys.modules["theater_rig.export"]
bpy.ops.import_scene.vrm(filepath=src)


def mtoon_image(m):
    d = detoon.read_mtoon(m)
    return d["base_image"] if d else None


mtoons = [m for m in bpy.data.materials if mtoon_image(m) is not None]
print(f"MToon materials with a texture: {len(mtoons)}; with a Principled image now: {sum(1 for m in bpy.data.materials if col.base_image(m))}")
target_image = None
problems = []


def slot():
    global target_image
    mat = next((m for m in bpy.data.materials if col.base_image(m) is not None), None)
    if mat is None:
        print("slot: no material Make Colour Slot can read (no Principled image)")
        return
    target_image = col.base_image(mat)
    grey, users = col.make_color_slot(target_image, 1)
    print(f"slot: {target_image.name} -> {grey.name} on {[u.name for u in users]}; MToon data still says: {[mtoon_image(u).name if mtoon_image(u) else None for u in users]}")


if order == "slot-first":
    slot(); detoon.detoonify()
else:
    detoon.detoonify(); slot()
print("after both, materials named Color1 use:", {m.name: (col.base_image(m).name if col.base_image(m) else None) for m in bpy.data.materials if "Color1" in m.name})
export.export_glb(bpy.context, out)
d = open(out, "rb").read()
n = struct.unpack("<I", d[12:16])[0]
g = json.loads(d[20:20 + n])
for mat in g["materials"]:
    if "Color1" not in mat["name"]:
        continue
    t = mat.get("pbrMetallicRoughness", {})
    tex = t.get("baseColorTexture")
    im = g["images"][g["textures"][tex["index"]]["source"]] if tex else None
    print(f"GLB {mat['name']}: image {im.get('name') if im else None!r}, factor {t.get('baseColorFactor')}, color_default {mat.get('extras', {}).get('color_default')}")
    if not im or "Color1" not in im.get("name", ""):
        problems.append(f"{mat['name']} lost its grey texture")
    if t.get("baseColorFactor") and any(abs(c - 1.0) > 1e-3 for c in t["baseColorFactor"][:3]):
        problems.append(f"{mat['name']} kept a colour factor")
print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")
