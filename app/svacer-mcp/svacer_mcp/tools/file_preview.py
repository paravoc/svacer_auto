"""
Advanced file preview tool - view source code from a snapshot.
Uses flat endpoint: GET /api/public/advanced_file_preview?file=...&snapshot=...&line=...
Does NOT require project_id or branch_id.
"""
import json
from typing import Annotated, Optional
from pydantic import Field
from mcp.server.fastmcp import Context

from ..api_client import SvacerAPIClient
from ..utils.validators import validate_uuid
from .descriptions import (
    GET_ADVANCED_FILE_PREVIEW,
    PARAM_PREVIEW_SNAPSHOT_ID,
    PARAM_FILE_PATH,
    PARAM_LINE,
    PARAM_BEFORE,
    PARAM_AFTER,
)


async def get_advanced_file_preview(
    snapshot_id: Annotated[str, Field(description=PARAM_PREVIEW_SNAPSHOT_ID)],
    file_path: Annotated[str, Field(description=PARAM_FILE_PATH)],
    ctx: Context,
    line: Annotated[int, Field(description=PARAM_LINE, ge=1)] = 1,
    before: Annotated[int, Field(description=PARAM_BEFORE, ge=0)] = 0,
    after: Annotated[int, Field(description=PARAM_AFTER, ge=0)] = 99999,
) -> str:
    api_client: SvacerAPIClient = ctx.request_context.lifespan_context["api_client"]

    validate_uuid(snapshot_id, "snapshot_id")

    preview = await api_client.get_advanced_file_preview(
        snapshot_id, file_path, line=line, before=before, after=after
    )
    return json.dumps(preview, indent=2, ensure_ascii=False)


get_advanced_file_preview.__doc__ = GET_ADVANCED_FILE_PREVIEW
