"""
Project groups tool - get a project group by name or ID.
"""
import json
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import Context

from ..api_client import SvacerAPIClient
from .descriptions import GET_PROJECT_GROUPS, PARAM_NAME_OR_ID


async def get_project_groups(
    name_or_id: Annotated[str, Field(description=PARAM_NAME_OR_ID)],
    ctx: Context,
) -> str:
    api_client: SvacerAPIClient = ctx.request_context.lifespan_context["api_client"]
    group = await api_client.get_project_groups(name_or_id)
    return json.dumps(group, indent=2, ensure_ascii=False)


get_project_groups.__doc__ = GET_PROJECT_GROUPS
