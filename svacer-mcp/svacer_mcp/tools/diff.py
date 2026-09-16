"""
Diff tool - compare two snapshots.
Uses flat endpoint: GET /api/public/diff?snapshot_v1=...&snapshot_v2=...
Does NOT require project_id or branch_id.
"""
import json
from typing import Annotated, Optional
from pydantic import Field
from mcp.server.fastmcp import Context

from ..api_client import SvacerAPIClient
from ..utils.response import apply_limit, select_fields
from ..utils.validators import validate_uuid
from .warnings import _format_warning
from .descriptions import (
    GET_DIFF,
    PARAM_BASE_SNAPSHOT_ID,
    PARAM_HEAD_SNAPSHOT_ID,
    PARAM_DIFF_LEVEL,
    PARAM_CHECKER_INFO,
    PARAM_DIFF_LIMIT,
    PARAM_FIELDS,
)

DEFAULT_DIFF_LIMIT = 20
# Category keys live under the top-level "markers" object, named per Svacer API:
# new_markers (added in v2), missing_markers (gone from v2), modified_markers
# (same id, changed context), matched_markers (unchanged in both).
MARKER_CATEGORIES = ("new_markers", "missing_markers", "modified_markers", "matched_markers")


async def get_diff(
    base_snapshot_id: Annotated[str, Field(description=PARAM_BASE_SNAPSHOT_ID)],
    ctx: Context,
    head_snapshot_id: Annotated[Optional[str], Field(description=PARAM_HEAD_SNAPSHOT_ID)] = None,
    level: Annotated[int, Field(description=PARAM_DIFF_LEVEL, ge=0)] = 0,
    checker_info: Annotated[Optional[bool], Field(description=PARAM_CHECKER_INFO)] = None,
    limit: Annotated[int, Field(description=PARAM_DIFF_LIMIT, ge=0)] = DEFAULT_DIFF_LIMIT,
    fields: Annotated[Optional[list[str]], Field(description=PARAM_FIELDS)] = None,
) -> str:
    api_client: SvacerAPIClient = ctx.request_context.lifespan_context["api_client"]

    validate_uuid(base_snapshot_id, "base_snapshot_id")
    if head_snapshot_id:
        validate_uuid(head_snapshot_id, "head_snapshot_id")

    diff_data = await api_client.get_diff(
        base_snapshot_id, head_snapshot_id, level=level,
        checker_info=bool(checker_info),
    )

    # Only wrap when full marker dicts are present (level>=2). At level<2 the
    # category lists are either empty or contain just IDs — already compact.
    if level >= 2 and isinstance(diff_data, dict):
        markers_block = diff_data.get("markers")
        if isinstance(markers_block, dict):
            for cat in MARKER_CATEGORIES:
                items = markers_block.get(cat)
                if not isinstance(items, list):
                    continue
                capped, total_count, truncated = apply_limit(items, limit)
                markers_block[cat] = {
                    "total_count": total_count,
                    "returned_count": len(capped),
                    "truncated": truncated,
                    "markers": [select_fields(_format_warning(m), fields) for m in capped],
                }

    return json.dumps(diff_data, indent=2, ensure_ascii=False)


get_diff.__doc__ = GET_DIFF
