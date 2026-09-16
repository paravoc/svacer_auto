"""
Helpers for shaping tool responses so they don't blow up LLM context.

Two pieces:
- select_fields: top-level whitelist on a formatted marker dict.
- apply_limit: cap a list, report total and truncated flag.

Both are intentionally simple — no dotted paths, no nested filtering. If we ever
need review.severity-style pruning, add it as a separate utility.
"""
from typing import Any, Optional

# Compact preset returned when fields=None. tool/mtid are intentionally omitted —
# they're rarely useful during review and add ~40 bytes per marker.
COMPACT_FIELDS = ["id", "warnClass", "file", "line", "msg", "function", "review"]

# Optional fields the user can opt into via the boolean flags (traces=True etc.).
# When fields=None, we keep these if they're already present in the marker dict.
OPTIONAL_FIELDS = ["traces", "checkerInfo", "review_history", "comments"]


def select_fields(marker: dict, fields: Optional[list[str]]) -> dict:
    """Apply a top-level field whitelist to a marker dict.

    fields=None       -> COMPACT_FIELDS plus any OPTIONAL_FIELDS already present
                         (caller opted into them via traces=True etc.).
    fields=["*"]      -> the marker dict unchanged.
    fields=["a","b"]  -> only listed top-level keys (missing keys are dropped silently).
    """
    if fields is None:
        keep = list(COMPACT_FIELDS)
        for k in OPTIONAL_FIELDS:
            if k in marker:
                keep.append(k)
        return {k: marker.get(k) for k in keep}

    if fields == ["*"] or "*" in fields:
        return dict(marker)

    return {k: marker[k] for k in fields if k in marker}


def build_filters_applied(
    base: dict,
    flags: dict,
    *,
    limit: Optional[int] = None,
    default_limit: Optional[int] = None,
    fields: Optional[list[str]] = None,
) -> dict:
    """Build the filters_applied summary block for get_warnings / get_markers.

    base    — filter args whose value is the user-supplied list (severity, file, …).
    flags   — opt-in toggles whose value is either bool or a string (traces, custom_filter, …).
    limit   — surfaced only when the caller passed something other than default_limit.
    fields  — surfaced when not None (None is the compact-preset signal).
    """
    applied: dict = {k: v for k, v in base.items() if v}
    for k, v in flags.items():
        if v:
            applied[k] = v
    if limit is not None and limit != default_limit:
        applied["limit"] = limit
    if fields is not None:
        applied["fields"] = fields
    return applied


def apply_limit(items: list, limit: int) -> tuple[list, int, bool]:
    """Cap a list. Returns (returned_items, total_count, truncated_flag).

    limit <= 0 disables the cap entirely — caller passed an explicit override.
    """
    total = len(items)
    if limit <= 0 or total <= limit:
        return items, total, False
    return items[:limit], total, True
