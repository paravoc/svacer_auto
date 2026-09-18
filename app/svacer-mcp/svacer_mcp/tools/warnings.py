"""
Warnings tool - get detailed warnings (fullmarkers) for a specific snapshot.
These use the nested endpoint: /projects/{pid}/branch/{bid}/snapshots/{sid}/fullmarkers
They require all three IDs: project_id, branch_id, snapshot_id.
For cross-project/cross-branch marker search, use get_markers instead.
"""
import json
from typing import Annotated, Optional
from pydantic import Field
from mcp.server.fastmcp import Context

from ..api_client import SvacerAPIClient
from ..utils.filters import FilterBuilder
from ..utils.response import apply_limit, build_filters_applied, select_fields
from ..utils.validators import validate_uuid
from .descriptions import (
    GET_WARNINGS,
    PARAM_PROJECT_ID,
    PARAM_BRANCH_ID,
    PARAM_SNAPSHOT_ID,
    PARAM_SEVERITY_WARNINGS,
    PARAM_REVIEW,
    PARAM_WARN_CLASS,
    PARAM_FILE,
    PARAM_TRACES_WARNINGS,
    PARAM_CHECKER_INFO,
    PARAM_REVIEW_HISTORY,
    PARAM_COMMENT_HISTORY,
    PARAM_CUSTOM_FILTER,
    PARAM_ADVANCED_FILTER,
    PARAM_LIMIT_WARNINGS,
    PARAM_FIELDS,
)

DEFAULT_WARNING_LIMIT = 30
# Heavy fallback when traces / review_history / comment_history are enabled.
# A single warning with traces can be 2–10 KB; cap tighter so the response stays usable.
DEFAULT_HEAVY_LIMIT = 8


def _format_warning(warning: dict) -> dict:
    """Return marker fields using the same field names as the Svacer REST API.

    Field names match Swagger exactly:
      id, invariant, warnClass, file, line, msg, tool, function, mtid
      review: nested object {status, severity, action}
    """
    result = {
        "id":        warning.get("id"),
        "invariant": warning.get("invariant"),
        "warnClass": warning.get("warnClass"),
        "file":      warning.get("file"),
        "line":      warning.get("line"),
        "msg":       warning.get("msg"),
        "tool":      warning.get("tool"),
        "function":  warning.get("function"),
        "mtid":      warning.get("mtid"),
        "review":    warning.get("review"),
    }
    if warning.get("traces") is not None:
        result["traces"] = warning["traces"]
    if warning.get("checkerInfo") is not None:
        result["checkerInfo"] = warning["checkerInfo"]
    if warning.get("review_history") is not None:
        result["review_history"] = warning["review_history"]
    if warning.get("comments") is not None:
        result["comments"] = warning["comments"]
    return result


def _apply_severity_filter(warnings: list, arguments: dict) -> list:
    """
    Filter warnings by severity client-side.
    Required only for /fullmarkers — that endpoint's server-side severity filter matches
    checker_severity (static checker property), not review.severity (manual review field).
    """
    severity_filter = set(arguments.get("severity") or [])
    if not severity_filter:
        return warnings
    return [w for w in warnings if (w.get("review") or {}).get("severity") in severity_filter]


async def get_warnings(
    project_id: Annotated[str, Field(description=PARAM_PROJECT_ID)],
    branch_id: Annotated[str, Field(description=PARAM_BRANCH_ID)],
    snapshot_id: Annotated[str, Field(description=PARAM_SNAPSHOT_ID)],
    ctx: Context,
    severity: Annotated[Optional[list[str]], Field(description=PARAM_SEVERITY_WARNINGS)] = None,
    review: Annotated[Optional[list[str]], Field(description=PARAM_REVIEW)] = None,
    warnClass: Annotated[Optional[list[str]], Field(description=PARAM_WARN_CLASS)] = None,
    file: Annotated[Optional[list[str]], Field(description=PARAM_FILE)] = None,
    traces: Annotated[Optional[bool], Field(description=PARAM_TRACES_WARNINGS)] = None,
    checker_info: Annotated[Optional[bool], Field(description=PARAM_CHECKER_INFO)] = None,
    review_history: Annotated[Optional[bool], Field(description=PARAM_REVIEW_HISTORY)] = None,
    comment_history: Annotated[Optional[bool], Field(description=PARAM_COMMENT_HISTORY)] = None,
    custom_filter: Annotated[Optional[str], Field(description=PARAM_CUSTOM_FILTER)] = None,
    advanced_filter: Annotated[Optional[str], Field(description=PARAM_ADVANCED_FILTER)] = None,
    limit: Annotated[Optional[int], Field(description=PARAM_LIMIT_WARNINGS, ge=0)] = None,
    fields: Annotated[Optional[list[str]], Field(description=PARAM_FIELDS)] = None,
) -> str:
    api_client: SvacerAPIClient = ctx.request_context.lifespan_context["api_client"]

    validate_uuid(project_id, "project_id")
    validate_uuid(branch_id, "branch_id")
    validate_uuid(snapshot_id, "snapshot_id")

    builder = FilterBuilder()
    if review:
        builder.with_review(review)
    if warnClass:
        builder.with_checker(warnClass)
    if file:
        builder.with_file(file)
    # NOTE: severity excluded from server filter — /fullmarkers severity param matches
    # checker_severity, not review.severity. Applied client-side below.
    filter_b64 = builder.build() or None

    allowed_marker_ids = None
    if advanced_filter:
        allowed_marker_ids = set(await api_client.apply_advanced_filter(
            advanced_filter, [snapshot_id]
        ))

    warnings_list = await api_client.get_warnings(
        project_id, branch_id, snapshot_id,
        filter_base64=filter_b64,
        traces=bool(traces),
        checker_info=bool(checker_info),
        review_history=bool(review_history),
        comment_history=bool(comment_history),
        custom_filter=custom_filter or None,
    )
    if allowed_marker_ids is not None:
        warnings_list = [
            warning for warning in warnings_list
            if str(warning.get("id")) in allowed_marker_ids
        ]
    warnings_list = _apply_severity_filter(warnings_list, {"severity": severity})

    heavy = bool(traces or review_history or comment_history)
    effective_limit = limit if limit is not None else (
        DEFAULT_HEAVY_LIMIT if heavy else DEFAULT_WARNING_LIMIT
    )
    capped, total_count, truncated = apply_limit(warnings_list, effective_limit)

    filters_applied = build_filters_applied(
        {"severity": severity, "warnClass": warnClass, "file": file, "review": review},
        {"traces": traces, "checker_info": checker_info,
         "review_history": review_history, "comment_history": comment_history,
         "custom_filter": custom_filter, "advanced_filter": advanced_filter},
        limit=limit,
        fields=fields,
    )

    result = {
        "total_count": total_count,
        "returned_count": len(capped),
        "truncated": truncated,
        "filters_applied": filters_applied,
        "warnings": [select_fields(_format_warning(w), fields) for w in capped],
    }

    return json.dumps(result, indent=2, ensure_ascii=False)


get_warnings.__doc__ = GET_WARNINGS
