"""The naming convention the renderer reads. An avatar carries no extra data:
its names say what each part is, and the renderer adds the behaviour.

- Body bones: Mixamo names (no "mixamorig:" prefix).
- Spring chains: spring_<kind>_<n>, colliders col_<shape>_<part>.
- Expressions: ARKit's 52 blendshape names.
- Colour groups: anything with Color<N> in its name follows colour slot N.
"""

import re

# Humanoid role (VRM's names, lowercased, no underscores) -> Mixamo bone name
MIXAMO = {
    "hips": "Hips",
    "spine": "Spine",
    "chest": "Spine1",
    "upperchest": "Spine2",
    "neck": "Neck",
    "head": "Head",
    "lefteye": "LeftEye",
    "righteye": "RightEye",
    "jaw": "Jaw",
}
for side, Side in (("left", "Left"), ("right", "Right")):
    MIXAMO.update({
        f"{side}shoulder": f"{Side}Shoulder",
        f"{side}upperarm": f"{Side}Arm",
        f"{side}lowerarm": f"{Side}ForeArm",
        f"{side}hand": f"{Side}Hand",
        f"{side}upperleg": f"{Side}UpLeg",
        f"{side}lowerleg": f"{Side}Leg",
        f"{side}foot": f"{Side}Foot",
        f"{side}toes": f"{Side}ToeBase",
    })
    for finger, Finger in (("thumb", "Thumb"), ("index", "Index"), ("middle", "Middle"), ("ring", "Ring"), ("little", "Pinky")):
        # VRM 0.x: proximal/intermediate/distal; VRM 1.0 thumb: metacarpal/proximal/distal
        segments = ("metacarpal", "proximal", "distal") if finger == "thumb" else ("proximal", "intermediate", "distal")
        for i, seg in enumerate(segments, 1):
            MIXAMO[f"{side}{finger}{seg}"] = f"{Side}Hand{Finger}{i}"
        if finger == "thumb":
            # VRM 0.x thumb names
            MIXAMO.setdefault(f"{side}thumbintermediate", f"{Side}HandThumb2")

# Roles every avatar needs for IK and look-at
REQUIRED_ROLES = [
    "hips", "spine", "neck", "head",
    "leftupperarm", "leftlowerarm", "lefthand", "rightupperarm", "rightlowerarm", "righthand",
    "leftupperleg", "leftlowerleg", "leftfoot", "rightupperleg", "rightlowerleg", "rightfoot",
]

# ARKit's 52 blendshapes
ARKIT = [
    "eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft", "eyeSquintLeft", "eyeWideLeft",
    "eyeBlinkRight", "eyeLookDownRight", "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight", "eyeSquintRight", "eyeWideRight",
    "jawForward", "jawLeft", "jawRight", "jawOpen",
    "mouthClose", "mouthFunnel", "mouthPucker", "mouthLeft", "mouthRight",
    "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthDimpleLeft", "mouthDimpleRight", "mouthStretchLeft", "mouthStretchRight",
    "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper",
    "mouthPressLeft", "mouthPressRight", "mouthLowerDownLeft", "mouthLowerDownRight", "mouthUpperUpLeft", "mouthUpperUpRight",
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight",
    "noseSneerLeft", "noseSneerRight",
    "tongueOut",
]

# ARKit name -> the VRoid shape key closest to it. Exact: the same motion;
# approximate: the nearest VRoid has (both sides at once, or a viseme).
VROID_TO_ARKIT = {
    "eyeBlinkLeft": ("Fcl_EYE_Close_L", "exact"),
    "eyeBlinkRight": ("Fcl_EYE_Close_R", "exact"),
    "eyeWideLeft": ("Fcl_EYE_Surprised", "approximate"),
    "eyeWideRight": ("Fcl_EYE_Surprised", "approximate"),
    "eyeSquintLeft": ("Fcl_EYE_Joy_L", "approximate"),
    "eyeSquintRight": ("Fcl_EYE_Joy_R", "approximate"),
    "jawOpen": ("Fcl_MTH_A", "approximate"),
    "mouthClose": ("Fcl_MTH_Close", "approximate"),
    "mouthFunnel": ("Fcl_MTH_O", "approximate"),
    "mouthPucker": ("Fcl_MTH_U", "approximate"),
    "mouthSmileLeft": ("Fcl_MTH_Fun", "approximate"),
    "mouthSmileRight": ("Fcl_MTH_Fun", "approximate"),
    "mouthFrownLeft": ("Fcl_MTH_Sorrow", "approximate"),
    "mouthFrownRight": ("Fcl_MTH_Sorrow", "approximate"),
    "mouthStretchLeft": ("Fcl_MTH_I", "approximate"),
    "mouthStretchRight": ("Fcl_MTH_I", "approximate"),
    "browDownLeft": ("Fcl_BRW_Angry", "approximate"),
    "browDownRight": ("Fcl_BRW_Angry", "approximate"),
    "browInnerUp": ("Fcl_BRW_Sorrow", "approximate"),
    "browOuterUpLeft": ("Fcl_BRW_Surprised", "approximate"),
    "browOuterUpRight": ("Fcl_BRW_Surprised", "approximate"),
}

# Spring chain kinds, by words found in VRM's group comment or the bone names
SPRING_KINDS = [
    ("hair", ("hair", "bang", "fringe", "ponytail", "twintail")),
    ("bust", ("bust", "breast", "chest_sec")),
    ("skirt", ("skirt", "dress")),
    ("tail", ("tail",)),
    ("ear", ("ear",)),
    ("ribbon", ("ribbon", "bow")),
    ("cloth", ("cloth", "coat", "cape", "sleeve", "hood")),
]


def spring_kind(*texts):
    """The kind of spring chain the given names describe ('misc' when none fits)."""
    blob = " ".join(t.lower() for t in texts if t)
    for kind, words in SPRING_KINDS:
        if any(w in blob for w in words):
            return kind
    return "misc"


COLOR_GROUP = re.compile(r"color(\d+)", re.IGNORECASE)


def color_slot(name):
    """The colour slot a name belongs to (Color3 -> 3), or None."""
    m = COLOR_GROUP.search(name or "")
    return int(m.group(1)) if m else None


def role_key(name):
    """VRM humanoid names in any spelling (leftUpperArm, left_upper_arm) -> leftupperarm."""
    return (name or "").replace("_", "").lower()
