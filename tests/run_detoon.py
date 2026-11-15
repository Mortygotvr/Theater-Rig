"""Headless test: detoonify a VRM, export a GLB, and check the GLB's materials
keep MToon's colours.

blender --background --python tests/run_detoon.py -- <model.vrm> <out.glb>
"""

import importlib.util
import json
import os
import struct
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = sys.argv[sys.argv.index("--") + 1:]
src, out = args[0], args[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
bpy.ops.import_scene.vrm(filepath=src)

spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
theater_rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = theater_rig
spec.loader.exec_module(theater_rig)
theater_rig.register()
detoon = sys.modules["theater_rig.detoon"]

before = {m.name: detoon.read_mtoon(m) for m in bpy.data.materials}
before = {k: v for k, v in before.items() if v}
print("operator:", bpy.ops.theater_rig.detoonify())
outlines_left = [f"{o.name}:{m.name}" for o in bpy.data.objects for m in getattr(o, "modifiers", []) if detoon.is_outline_modifier(m)]

bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_extras=True)

with open(out, "rb") as f:
    data = f.read()
length = struct.unpack_from("<I", data, 12)[0]
gltf = json.loads(data[20:20 + length])
images = gltf.get("images", [])
textures = gltf.get("textures", [])


def image_of(info):
    if not info:
        return None
    return images[textures[info["index"]]["source"]].get("name")


def close(a, b, tol=0.01):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


problems = 0
by_name = {m["name"]: m for m in gltf.get("materials", [])}
for name, d in sorted(before.items()):
    m = by_name.get(name)
    if m is None:
        print(f"!! {name}: not in the GLB (unused?)")
        continue
    pbr = m.get("pbrMetallicRoughness", {})
    got = {
        "base": pbr.get("baseColorFactor", [1, 1, 1, 1])[:3],
        "base_img": image_of(pbr.get("baseColorTexture")),
        "emis": m.get("emissiveFactor", [0, 0, 0]),
        "emis_img": image_of(m.get("emissiveTexture")),
        "alpha": m.get("alphaMode", "OPAQUE"),
        # glTF's default; exporters leave it out at 0.5
        "cutoff": m.get("alphaCutoff", 0.5),
        "shade": m.get("extras", {}).get("shade_color"),
    }
    want_emis = [0, 0, 0] if detoon._is_black(d["emissive"]) else list(d["emissive"][:3])
    checks = {
        "base colour": close(got["base"], d["base_color"][:3]),
        "base texture": got["base_img"] == (d["base_image"].name if d["base_image"] else None),
        "emission": close(got["emis"], want_emis),
        "emission texture": got["emis_img"] == (d["emissive_image"].name if d["emissive_image"] and want_emis != [0, 0, 0] else None),
        "alpha mode": got["alpha"] == d["alpha_mode"],
        "shade colour": got["shade"] is not None and close(got["shade"], d["shade_color"][:3]),
    }
    if d["alpha_mode"] == "MASK":
        checks["cutoff"] = got["cutoff"] is not None and abs(got["cutoff"] - d["alpha_cutoff"]) < 0.01
    bad = [k for k, ok in checks.items() if not ok]
    problems += len(bad)
    print(("OK " if not bad else "!! ") + name + ("" if not bad else f"  wrong: {bad}  got {got}  want base {d['base_color'][:3]} emis {want_emis} alpha {d['alpha_mode']}/{d['alpha_cutoff']:.2f}"))

print(f"outline modifiers left: {outlines_left}")
print(f"RESULT: {len(before)} MToon materials, {problems} problem(s)")
