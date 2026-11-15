"""Headless test of Make Colour Slot and Export GLB on a VRM.

blender --background --python tests/run_colour_export.py -- <model.vrm> <out.glb>
"""

import importlib.util
import json
import os
import struct
import sys

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = sys.argv[sys.argv.index("--") + 1:]
src, out = args[0], args[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
bpy.ops.import_scene.vrm(filepath=src)

spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = rig
spec.loader.exec_module(rig)
rig.register()
col = sys.modules["theater_rig.colour"]
an = sys.modules["theater_rig.analyse"]
ops = bpy.ops.theater_rig
problems = []

ops.detoonify()
ops.rename_mixamo()
ops.rename_springs()

# Pick from Selected: the Hair object, its hair material active
hair = bpy.data.objects["Hair"]
idx = next(i for i, m in enumerate(hair.data.materials) if m and "hair" in m.name.lower() and col.base_image(m))
hair.active_material_index = idx
bpy.context.view_layer.objects.active = hair
print("pick:", ops.pick_texture())
st = bpy.context.scene.theater_rig
orig = st.color_image
print(f"  picked {orig.name} ({orig.size[0]}x{orig.size[1]})")
users_before = [m.name for m in bpy.data.materials if col.base_image(m) == orig]

w, h = orig.size
px = np.empty(w * h * 4, dtype=np.float32)
orig.pixels.foreach_get(px)
px = px.reshape(-1, 4)
seen = px[:, 3] > 0.5
_, mix0 = col._base_link(hair.data.materials[idx])
old_factor = np.array(mix0.inputs["B"].default_value[:3]) if mix0 else np.ones(3)
orig_mean = px[seen, :3].mean(axis=0) * old_factor   # what the material showed

st.color_slot = 2
print("make_color_slot:", ops.make_color_slot())
grey = st.color_image
print(f"  grey image: {grey.name}, packed {grey.packed_file is not None}")
if "Color2" not in grey.name:
    problems.append(f"grey image not named Color2: {grey.name}")
g = np.empty(w * h * 4, dtype=np.float32)
grey.pixels.foreach_get(g)
g = g.reshape(-1, 4)
if np.abs(g[:, 0] - g[:, 1]).max() > 1e-6 or np.abs(g[:, 1] - g[:, 2]).max() > 1e-6:
    problems.append("grey image isn't grey")
if np.abs(g[:, 3] - px[:, 3]).max() > 1e-6:
    problems.append("alpha changed")
mats = [m for m in bpy.data.materials if col.base_image(m) == grey]
print(f"  materials now on it: {[m.name for m in mats]} (were {users_before})")
if len(mats) != len(users_before) or not all("Color2" in m.name for m in mats):
    problems.append("materials not all moved to the grey texture / renamed")
# Grey x tint should give back the original colour on average
_, mix = col._base_link(mats[0])
tint = np.array(mix.inputs["B"].default_value[:3])
recon = (g[seen, :3] * tint).mean(axis=0)
print(f"  tint {np.round(tint, 3)}; average colour original {np.round(orig_mean, 3)}, grey x tint {np.round(recon, 3)}")
if np.abs(recon - orig_mean).max() > 0.03:
    problems.append("grey x tint drifts from the original colour")
rep = an.analyse()
print(f"  colour slots after: {sorted(rep.color_groups)}")
if 2 not in rep.color_groups:
    problems.append("Analyse doesn't see Color2")

# Export (ExportHelper's execute, as after the file dialog)
print("export:", ops.export(filepath=out))
data = open(out, "rb").read()
gltf = json.loads(data[20:20 + struct.unpack_from("<I", data, 12)[0]])
node_names = [n.get("name", "") for n in gltf["nodes"]]
meshes = [n for n in gltf["nodes"] if "mesh" in n]
print(f"  GLB: {len(gltf['nodes'])} nodes, {len(meshes)} meshes, {len(gltf.get('skins', []))} skin(s), animations {len(gltf.get('animations', []))}")
gm = next((m for m in gltf["materials"] if "Color2" in m["name"]), None)
if gm is None:
    problems.append("no Color2 material in the GLB")
else:
    factor = gm["pbrMetallicRoughness"].get("baseColorFactor")
    tex_i = gm["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    img_name = gltf["images"][gltf["textures"][tex_i]["source"]]["name"]
    print(f"  GLB {gm['name']}: factor {factor}, image {img_name}, extras {gm.get('extras')}")
    if not factor or abs(factor[0] - tint[0]) > 1e-3:
        problems.append("tint not exported as the base colour factor")
    if "Color2" not in img_name:
        problems.append("GLB image not named Color2")
    if "shade_color" not in gm.get("extras", {}):
        problems.append("shade_color missing")
face_mesh = gltf["meshes"][next(n["mesh"] for n in gltf["nodes"] if n.get("name") == "Face")]
targets = len(face_mesh.get("extras", {}).get("targetNames", []))
print(f"  Face shape keys in GLB: {targets}")
if targets < 52:
    problems.append("shape keys missing from the GLB")
if not gltf.get("skins"):
    problems.append("no skin")
if gltf.get("animations"):
    problems.append("animations exported")
sp = next((n for n in gltf["nodes"] if n.get("name") == "spring_hair_1_0"), None)
if not sp or "spring_stiffness" not in sp.get("extras", {}):
    problems.append("spring settings missing")
for n in ("Hips", "LeftHandThumb1", "Head"):
    if n not in node_names:
        problems.append(f"bone {n} missing")

for p in problems:
    print("!!", p)
print(f"RESULT: {len(problems)} problem(s)")
