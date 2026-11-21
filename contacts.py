"""Contact frames: the frames of an animation where it touches something (a
pie lands on the face, a sword hits). Theater Scene runs a GLB prefab
redeem's contact section (sound, shake, the avatar's reaction) at each, as
a throwable's on impact, with no physics: the animation is baked.

They're markers named "contact" (or "contact 2", "Contact: splash"…, any
name starting with it, any case): the timeline's, for whichever animation
spans their frame, or an action's own pose markers, for that one. The glTF
export writes each animation's as its extras, `theater_contacts`: seconds
from the animation's first frame (as Theater Puppet times it)."""

import bpy

WORD = "contact"
EXTRA = "theater_contacts"


def is_contact(marker):
    return marker.name.strip().lower().startswith(WORD)


def fps(scene):
    return scene.render.fps / (scene.render.fps_base or 1.0)


def times(action, scene):
    """An action's contacts: seconds from its first frame, in order. Its own
    pose markers when it has contact ones, else the timeline's in its range."""
    start, end = action.frame_range
    own = [m.frame for m in getattr(action, "pose_markers", []) if is_contact(m)]
    frames = own if own else [m.frame for m in scene.timeline_markers if is_contact(m) and start - 1e-4 <= m.frame <= end + 1e-4]
    rate = fps(scene)
    return sorted(round((f - start) / rate, 6) for f in frames)


class glTF2ExportUserExtension:
    """The glTF exporter's hook: each animation's contacts in its extras."""

    def gather_gltf_hook(self, active_scene_idx, scenes, animations, export_settings):
        scene = bpy.context.scene
        for anim in animations or []:
            action = bpy.data.actions.get(getattr(anim, "name", "") or "")
            if action is None:
                continue
            found = times(action, scene)
            if not found:
                continue
            extras = anim.extras if isinstance(getattr(anim, "extras", None), dict) else {}
            extras[EXTRA] = found
            anim.extras = extras
