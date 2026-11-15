"""Headless test: import a VRM or GLB and print the Analyse report.

blender --background --python tests/run_analyse.py -- <model.vrm|.glb>
"""

import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))

path = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
if path.lower().endswith(".vrm"):
    bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.vrm")
    bpy.ops.import_scene.vrm(filepath=path)
else:
    bpy.ops.import_scene.gltf(filepath=path)

pkg = __import__(os.path.basename(ROOT).replace("-", "_")) if False else None
import importlib.util

spec = importlib.util.spec_from_file_location("theater_rig", os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
theater_rig = importlib.util.module_from_spec(spec)
sys.modules["theater_rig"] = theater_rig
spec.loader.exec_module(theater_rig)
theater_rig.register()

result = bpy.ops.theater_rig.analyse()
print("operator:", result)
print("=" * 70)
print(bpy.data.texts["Theater Rig report"].as_string())
