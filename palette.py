"""A texture's main colours, and a mask of the ones picked: for a colour slot
that recolours only some colours of a texture (her red, not the yellow
stripe; the grey top, not its orange trims), the rest kept as painted.

No Blender here (numpy only): colour.py hands it the pixels."""

import numpy as np

# At most this many colours listed; two closer than MERGE are one
MAX_COLOURS = 8
MERGE = 0.10
# A colour under this share of the texture isn't listed (a stray pixel)
MIN_SHARE = 0.002


def _sample(rgba, most=65536):
    """Opaque pixels (rgb), at most `most` of them, evenly picked."""
    seen = rgba[:, 3] > 0.5
    px = rgba[seen, :3]
    if len(px) > most:
        px = px[:: len(px) // most]
    return px


def _space(rgb):
    """A space where distances look like differences: lightness weighs most,
    and a grey's hue doesn't count"""
    w = np.array([0.30, 0.59, 0.11])
    lum = rgb @ w
    chroma = rgb - lum[..., None]
    return np.concatenate([lum[..., None] * 1.6, chroma], axis=-1)


def colours(rgba):
    """[(rgb, share)] of the texture's main colours, most first. `rgba`:
    (n, 4) floats 0-1."""
    px = _sample(rgba)
    if len(px) == 0:
        return []
    x = _space(px)
    k = min(MAX_COLOURS + 4, len(px))
    # Seeds spread out (each the farthest from those before), then k-means
    centres = [x[0]]
    d = np.linalg.norm(x - centres[0], axis=1)
    for _ in range(k - 1):
        i = int(d.argmax())
        if d[i] < 1e-3:
            break
        centres.append(x[i])
        d = np.minimum(d, np.linalg.norm(x - x[i], axis=1))
    c = np.array(centres)
    for _ in range(12):
        lab = np.linalg.norm(x[:, None, :] - c[None], axis=2).argmin(1)
        for j in range(len(c)):
            m = lab == j
            if m.any():
                c[j] = x[m].mean(0)
    lab = np.linalg.norm(x[:, None, :] - c[None], axis=2).argmin(1)
    groups = [(px[lab == j].mean(0), (lab == j).mean(), x[lab == j].mean(0)) for j in range(len(c)) if (lab == j).any()]
    # Close ones merged (the biggest takes the other)
    groups.sort(key=lambda g: -g[1])
    out = []
    for rgb, share, pos in groups:
        for o in out:
            if np.linalg.norm(o[2] - pos) < MERGE:
                o[1] += share
                break
        else:
            out.append([rgb, share, pos])
    found = [(tuple(float(v) for v in rgb), float(share)) for rgb, share, _ in out[: MAX_COLOURS + 4] if share >= MIN_SHARE]
    return families(found)[:MAX_COLOURS]


def _hue_sat(rgb):
    r, g, b = rgb
    mx, mn = max(rgb), min(rgb)
    sat = (mx - mn) / mx if mx > 0 else 0.0
    if mx == mn:
        return 0.0, sat
    d = mx - mn
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60.0, sat


# Colours of one hue (her red, its light streak, its dark edge) are one
# family: picked together. Greys (no hue) stay apart by lightness.
FAMILY_HUE = 25.0
GREY_SAT = 0.18


def families(found):
    """[(rgb, share, [member rgbs])] from [(rgb, share)] (most first): one
    per hue for colours, one per colour for greys."""
    out = []
    for rgb, share in found:
        h, s = _hue_sat(rgb)
        for f in out:
            fh, fs = _hue_sat(f[0])
            if s >= GREY_SAT and fs >= GREY_SAT and min(abs(h - fh), 360 - abs(h - fh)) < FAMILY_HUE:
                f[1] += share
                f[2].append(rgb)
                break
        else:
            out.append([rgb, share, [rgb]])
    return [(tuple(f[0]), f[1], f[2]) for f in out]


def mask(rgba, listed, picked):
    """How much each pixel is one of the `picked` colours (0-1), from
    `listed` (the texture's colour families: colours() or [member rgbs]
    each): a pixel takes after the nearest listed colour; between a picked
    one and another (an anti-aliased edge), partly. Transparent pixels: 0."""
    rgb = rgba[:, :3]
    x = _space(rgb)
    members, flags = [], []
    for fam, on in zip(listed, picked):
        each = fam[2] if isinstance(fam, (tuple, list)) and len(fam) == 3 and isinstance(fam[2], list) else [fam]
        members += [tuple(m) for m in each]
        flags += [bool(on)] * len(each)
    pos = _space(np.array(members, dtype=np.float32))
    picked = np.array(flags, dtype=bool)
    if picked.all():
        return (rgba[:, 3] > 0).astype(np.float32) * rgba[:, 3]
    if not picked.any():
        return np.zeros(len(rgba), dtype=np.float32)
    dist = np.linalg.norm(x[:, None, :] - pos[None], axis=2)
    near_in = dist[:, picked].min(1)
    near_out = dist[:, ~picked].min(1)
    t = near_out / np.maximum(near_in + near_out, 1e-6)
    a = np.clip((t - 0.35) / 0.30, 0.0, 1.0)
    return (a * a * (3 - 2 * a)) * rgba[:, 3]
