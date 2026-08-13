# render_resolution.py
# Aspect ratio presets for Create/Edit Film and the derived pixel
# dimensions GAAPlayblastTool_V7.py actually renders at. Films store a
# PRESET ("16:9", "2.39:1", ...), not explicit width/height -- dimensions
# are derived here against a fixed base height, so the same preset always
# produces the same pixel size and nothing has to be re-stored if the
# derivation formula ever changes.

ASPECT_RATIO_PRESETS = [
    {"value": "16:9", "label": "16:9 (Widescreen)"},
    {"value": "1.85:1", "label": "1.85:1 (Academy Flat)"},
    {"value": "2.39:1", "label": "2.39:1 (Anamorphic / Cinemascope)"},
    {"value": "4:3", "label": "4:3 (Classic / Academy)"},
    {"value": "1:1", "label": "1:1 (Square)"},
]

DEFAULT_ASPECT_RATIO = "16:9"

# 1080 for the full "Submit" render, matching the resolution
# GAAPlayblastTool_V7.py has always hardcoded for 16:9 -- so existing
# films render pixel-identical to before until a coordinator picks a
# different preset. Personal "Movie For You" copies render at half this.
BASE_HEIGHT = 1080


def resolve_render_dimensions(aspect_ratio, base_height=BASE_HEIGHT):
    """
    Returns (width, height) for the given aspect ratio preset (e.g.
    "16:9", "2.39:1"), derived against base_height. Width is rounded to
    the nearest even number, since video encoders expect even dimensions.
    Falls back to 16:9 for anything missing or malformed.
    """
    try:
        w_ratio, h_ratio = (float(part) for part in (aspect_ratio or DEFAULT_ASPECT_RATIO).split(":"))
        if w_ratio <= 0 or h_ratio <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        w_ratio, h_ratio = 16.0, 9.0

    width = round(base_height * (w_ratio / h_ratio) / 2) * 2
    return width, base_height
