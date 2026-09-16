"""
Statistics tool - get aggregated warning counts for a project snapshot.
"""
import json
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import Context

from ..api_client import SvacerAPIClient
from ..utils.validators import validate_uuid
from .descriptions import (
    GET_PROJECT_STATS,
    PARAM_PROJECT_ID,
    PARAM_BRANCH_ID,
    PARAM_SNAPSHOT_ID,
)


async def get_project_stats(
    project_id: Annotated[str, Field(description=PARAM_PROJECT_ID)],
    branch_id: Annotated[str, Field(description=PARAM_BRANCH_ID)],
    snapshot_id: Annotated[str, Field(description=PARAM_SNAPSHOT_ID)],
    ctx: Context,
) -> str:
    api_client: SvacerAPIClient = ctx.request_context.lifespan_context["api_client"]

    validate_uuid(project_id, "project_id")
    validate_uuid(branch_id, "branch_id")
    validate_uuid(snapshot_id, "snapshot_id")

    stats = await api_client.get_project_stats(project_id, branch_id, snapshot_id)
    return json.dumps(stats, indent=2, ensure_ascii=False)


get_project_stats.__doc__ = GET_PROJECT_STATS
