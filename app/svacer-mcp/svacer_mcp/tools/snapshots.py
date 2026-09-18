"""
Snapshots tool - list snapshots for a project branch.
Use after get_projects to get snapshot_id needed by markers, diff, file_preview tools.
"""
import asyncio
import json
import re
from typing import Annotated, Optional
from pydantic import Field
from mcp.server.fastmcp import Context

from ..api_client import SvacerAPIClient
from ..utils.filters import FilterBuilder
from ..utils.validators import validate_uuid
from .descriptions import GET_SNAPSHOTS, PARAM_PROJECT_ID, PARAM_BRANCH_ID, PARAM_NAME_FILTER


_COMMIT_PREFIX_RE = re.compile(r"^([0-9a-fA-F]{7,40})\s*-")


async def _count_markers(
    api_client: SvacerAPIClient,
    project_id: str,
    branch_id: str,
    snapshot_id: Optional[str],
) -> int:
    if not snapshot_id:
        return 0
    filter_b64 = FilterBuilder().build_markers_filter(project_id, branch_id, snapshot_id)
    response = await api_client.get_markers(
        project_id, branch_id, snapshot_id, filter_base64=filter_b64
    )
    return sum(len(item.get("markers", [])) for item in response)


def _extract_commit(details: dict) -> Optional[str]:
    """Look up a commit hash in snapshot.details.custom_properties.

    The field isn't on every snapshot and the custom-property names vary
    between projects, so we just pick the first property whose name contains
    "commit". Handles both shapes seen in the wild: a flat ``{name: value}``
    mapping and a list of ``{"name": ..., "value": ...}`` records.
    """
    if not isinstance(details, dict):
        return None
    props = details.get("custom_properties")
    if isinstance(props, dict):
        for key, value in props.items():
            if isinstance(key, str) and "commit" in key.lower() and value:
                return str(value)
    elif isinstance(props, list):
        for item in props:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("key")
            value = item.get("value")
            if isinstance(name, str) and "commit" in name.lower() and value:
                return str(value)
    return None


def _extract_commit_from_name(name: str) -> Optional[str]:
    """Fallback: snapshot.name may start with a short commit hash followed by
    `` - ``, e.g. ``"e20758f0 - Mon, 13 Dec 2021 …"``. Returns None when the
    name doesn't start with a 7+ hex prefix.
    """
    if not isinstance(name, str):
        return None
    m = _COMMIT_PREFIX_RE.match(name)
    return m.group(1) if m else None


async def get_snapshots(
    project_id: Annotated[str, Field(description=PARAM_PROJECT_ID)],
    branch_id: Annotated[str, Field(description=PARAM_BRANCH_ID)],
    ctx: Context,
    name_filter: Annotated[Optional[str], Field(description=PARAM_NAME_FILTER)] = None,
) -> str:
    api_client: SvacerAPIClient = ctx.request_context.lifespan_context["api_client"]

    validate_uuid(project_id, "project_id")
    validate_uuid(branch_id, "branch_id")

    filter_b64 = FilterBuilder().build_snapshots_filter(
        project_id, branch_id, name=name_filter
    )
    raw = await api_client.get_snapshots_flat(filter_b64)

    flat_snapshots = [s for group in raw for s in group.get("snapshots", [])]

    # N+1 marker counts: fire concurrently rather than serially. Order of
    # returned counts matches flat_snapshots, so zip is safe.
    counts = await asyncio.gather(*(
        _count_markers(api_client, project_id, branch_id, s.get("id"))
        for s in flat_snapshots
    ))

    formatted_snapshots = []
    for snapshot, markers_count in zip(flat_snapshots, counts):
        name = snapshot.get("name", "")
        commit_hash = (
            _extract_commit(snapshot.get("details") or {})
            or _extract_commit_from_name(name)
        )
        formatted_snapshots.append({
            "snapshot_id": snapshot.get("id"),
            "name": name,
            "import_time": snapshot.get("import_time"),
            "commit_hash": commit_hash,
            "markers_count": markers_count,
            "link": snapshot.get("link"),
        })

    return json.dumps(formatted_snapshots, indent=2, ensure_ascii=False)


get_snapshots.__doc__ = GET_SNAPSHOTS
