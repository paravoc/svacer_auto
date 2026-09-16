"""
Projects tool - list all projects with branches.
START HERE: use this tool first to get project_id and branch_id needed by other tools.
"""

import json
from mcp.server.fastmcp import Context

from ..api_client import SvacerAPIClient
from .descriptions import GET_PROJECTS


def _extract_string(value, default="unknown"):
    """Accept both plain strings and null.String wrapper objects.

    Svacer API may return either format depending on server version:
      - Swagger format: {"string": "admin", "valid": true}
      - Wiki-documented format: "admin"
    """
    if isinstance(value, dict):
        return value.get("string") or default
    return value or default


async def get_projects(ctx: Context) -> str:
    api_client: SvacerAPIClient = ctx.request_context.lifespan_context["api_client"]
    projects = await api_client.get_projects()

    formatted_projects = []
    for item in projects:
        project = item["project"]
        branches = item["branches"]

        formatted_projects.append(
            {
                "project_id": project["id"],
                "project_name": project["name"],
                "created": project["time"],
                "created_by": _extract_string(project.get("created_by")),
                "branches": [
                    {
                        "branch_id": b["id"],
                        "branch_name": b["name"],
                        "created": b["time"],
                    }
                    for b in branches
                ],
            }
        )

    return json.dumps(formatted_projects, indent=2, ensure_ascii=False)


get_projects.__doc__ = GET_PROJECTS
