"""Impact frames: the frames of an animation where it hits something (a pie
lands on the face, a sword hits). Theater Scene runs a GLB prefab redeem's
Impact settings (Impact Audio, Screen Shake and Impact Reaction On Impact)
at each, as a throwable's hit, with no physics: the animation is baked.

They're markers named "impact" (or "impact 2", "Impact: splash"…, any name
starting with it, any case; "contact", their old name, too): the timeline's,
for whichever animation spans their frame, or an action's own pose markers,
for that one. The glTF export writes each animation's as its extras,
`theater_contacts` (the file's name for them, kept so older GLBs still
work): seconds from the animation's first frame (as Theater Puppet times it)."""

import bpy

WORDS = ("impact", "contact")
EXTRA = "theater_contacts"
# Export Animations (anim_export.py): (the clip's name, its action) while one
# action is exported alone (the exporter calls it "Animation")
export_as = None


def is_contact(marker):
    return marker.name.strip().lower().startswith(WORDS)


def fps(scene):
    return scene.render.fps / (scene.render.fps_base or 1.0)


def times(action, scene):
    """An action's impacts: seconds from its first frame, in order. Its own
    pose markers when it has impact ones, else the timeline's in its range."""
    start, end = action.frame_range
    own = [m.frame for m in getattr(action, "pose_markers", []) if is_contact(m)]
    frames = own if own else [m.frame for m in scene.timeline_markers if is_contact(m) and start - 1e-4 <= m.frame <= end + 1e-4]
    rate = fps(scene)
    return sorted(round((f - start) / rate, 6) for f in frames)


class glTF2ExportUserExtension:
    """The glTF exporter's hook: each animation's impacts in its extras."""

    def gather_gltf_hook(self, active_scene_idx, scenes, animations, export_settings):
        scene = bpy.context.scene
        for anim in animations or []:
            action = bpy.data.actions.get(getattr(anim, "name", "") or "")
            if action is None and export_as is not None and len(animations) == 1:
                anim.name, action = export_as
            if action is None:
                continue
            found = times(action, scene)
            if not found:
                continue
            extras = anim.extras if isinstance(getattr(anim, "extras", None), dict) else {}
            extras[EXTRA] = found
            anim.extras = extras
