"""
Markers tool - lightweight marker listing with flexible filters.
Uses flat endpoint: GET /api/public/markers?filters=<base64>
Supports cross-project filtering by project/branch/snapshot name patterns.
"""
import json
from typing import Annotated, Optional
from pydantic import Field
from mcp.server.fastmcp import Context

from ..api_client import SvacerAPIClient
from ..utils.filters import FilterBuilder
from ..utils.response import apply_limit, build_filters_applied, select_fields
from ..utils.validators import validate_uuid
from .warnings import _format_warning, _apply_severity_filter
from .descriptions import (
    GET_MARKERS,
    PARAM_PROJECT_ID,
    PARAM_BRANCH_ID,
    PARAM_SNAPSHOT_ID,
    PARAM_SEVERITY_MARKERS,
    PARAM_REVIEW,
    PARAM_WARN_CLASS,
    PARAM_FILE,
    PARAM_TRACES_MARKERS,
    PARAM_CHECKER_INFO,
    PARAM_REVIEW_HISTORY,
    PARAM_COMMENT_HISTORY,
    PARAM_CUSTOM_FILTER,
    PARAM_ADVANCED_FILTER,
    PARAM_LIMIT,
    PARAM_FIELDS,
)

DEFAULT_MARKER_LIMIT = 30


async def get_markers(
    project_id: Annotated[str, Field(description=PARAM_PROJECT_ID)],
    branch_id: Annotated[str, Field(description=PARAM_BRANCH_ID)],
    snapshot_id: Annotated[str, Field(description=PARAM_SNAPSHOT_ID)],
    ctx: Context,
    severity: Annotated[Optional[list[str]], Field(description=PARAM_SEVERITY_MARKERS)] = None,
    review: Annotated[Optional[list[str]], Field(description=PARAM_REVIEW)] = None,
    warnClass: Annotated[Optional[list[str]], Field(description=PARAM_WARN_CLASS)] = None,
    file: Annotated[Optional[list[str]], Field(description=PARAM_FILE)] = None,
    traces: Annotated[Optional[bool], Field(description=PARAM_TRACES_MARKERS)] = None,
    checker_info: Annotated[Optional[bool], Field(description=PARAM_CHECKER_INFO)] = None,
    review_history: Annotated[Optional[bool], Field(description=PARAM_REVIEW_HISTORY)] = None,
    comment_history: Annotated[Optional[bool], Field(description=PARAM_COMMENT_HISTORY)] = None,
    custom_filter: Annotated[Optional[str], Field(description=PARAM_CUSTOM_FILTER)] = None,
    advanced_filter: Annotated[Optional[str], Field(description=PARAM_ADVANCED_FILTER)] = None,
    limit: Annotated[int, Field(description=PARAM_LIMIT, ge=0)] = DEFAULT_MARKER_LIMIT,
    fields: Annotated[Optional[list[str]], Field(description=PARAM_FIELDS)] = None,
) -> str:
    api_client: SvacerAPIClient = ctx.request_context.lifespan_context["api_client"]

    validate_uuid(project_id, "project_id")
    validate_uuid(branch_id, "branch_id")
    validate_uuid(snapshot_id, "snapshot_id")

    # NOTE: severity excluded from server-side filter — /markers severity param matches
    # checker_severity, not review.severity (same quirk as /fullmarkers). Applied client-side below.
    builder = FilterBuilder()
    if review:
        builder.with_review(review)
    if warnClass:
        builder.with_checker(warnClass)
    if file:
        builder.with_file(file)

    filter_b64 = builder.build_markers_filter(project_id, branch_id, snapshot_id)

    allowed_marker_ids = None
    if advanced_filter:
        allowed_marker_ids = set(await api_client.apply_advanced_filter(
            advanced_filter, [snapshot_id]
        ))

    raw_response = await api_client.get_markers(
        project_id, branch_id, snapshot_id,
        filter_base64=filter_b64,
        traces=bool(traces),
        checker_info=bool(checker_info),
        review_history=bool(review_history),
        comment_history=bool(comment_history),
        custom_filter=custom_filter or None,
    )

    all_markers = []
    for item in raw_response:
        all_markers.extend(item.get("markers", []))
    if allowed_marker_ids is not None:
        all_markers = [m for m in all_markers if str(m.get("id")) in allowed_marker_ids]
        if not any((severity, review, warnClass, file, custom_filter)):
            returned_ids = {str(m.get("id")) for m in all_markers}
            if allowed_marker_ids - returned_ids:
                raise ValueError("Incomplete inventory: not all advanced-filter marker IDs were returned")
    all_markers = _apply_severity_filter(all_markers, {"severity": severity})

    capped, total_count, truncated = apply_limit(all_markers, limit)

    filters_applied = build_filters_applied(
        {"severity": severity, "review": review, "warnClass": warnClass, "file": file},
        {"traces": traces, "checker_info": checker_info,
         "review_history": review_history, "comment_history": comment_history,
         "custom_filter": custom_filter, "advanced_filter": advanced_filter},
        limit=limit,
        default_limit=DEFAULT_MARKER_LIMIT,
        fields=fields,
    )

    result = {
        "total_count": total_count,
        "returned_count": len(capped),
        "truncated": truncated,
        "filters_applied": filters_applied,
        "markers": [select_fields(_format_warning(m), fields) for m in capped],
    }

    return json.dumps(result, indent=2, ensure_ascii=False)


get_markers.__doc__ = GET_MARKERS
