"""
HTTP client for Svacer Public REST API
"""
import httpx
from typing import List, Dict, Any, Optional

from .auth import SvacerAuth
from .exceptions import SvacerAPIError


class SvacerAPIClient:
    """Client for Svacer Public REST API.

    Implements context-manager protocol so resources are released properly::

        async with SvacerAPIClient(auth) as client:
            ...
    """

    def __init__(self, auth: SvacerAuth):
        self.auth = auth
        self.base_url = auth.url
        self.timeout = auth.timeout
        # httpx.AsyncClient is created lazily inside the running event loop
        # via connect()/__aenter__; constructing it in __init__ would couple
        # transport setup to whatever loop happens to be current at import time.
        self.client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Create the underlying httpx.AsyncClient. Idempotent."""
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout)
            # Let auth reuse our httpx client for token refresh requests
            self.auth._http_client = self.client

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()
        return False

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Perform request, on 401 refresh token and retry once."""
        if self.client is None:
            await self.connect()
        kwargs.setdefault("headers", await self.auth.get_headers())
        try:
            response = await self.client.request(method, url, **kwargs)
            if response.status_code == 401:
                self.auth.invalidate_token()
                kwargs["headers"] = await self.auth.get_headers()
                response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            raise SvacerAPIError(
                f"API request {method} {url} failed with status {e.response.status_code}"
            ) from e
        except httpx.HTTPError as e:
            raise SvacerAPIError(
                f"API request {method} {url} failed: {e}"
            ) from e

    @staticmethod
    def _optional_params(
        *,
        traces: bool = False,
        checker_info: bool = False,
        review_history: bool = False,
        comment_history: bool = False,
        custom_filter: Optional[str] = None,
    ) -> Dict[str, str]:
        """Common opt-in flags shared by /fullmarkers and /markers endpoints."""
        out: Dict[str, str] = {}
        if traces:
            out["traces"] = "true"
        if checker_info:
            out["checker_info"] = "true"
        if review_history:
            out["review_history"] = "true"
        if comment_history:
            out["comment_history"] = "true"
        if custom_filter:
            out["custom_filter"] = custom_filter
        return out

    @staticmethod
    def _json_or_empty(response: httpx.Response, empty_factory=list):
        """Parse JSON body, returning *empty_factory()* on 204 / empty body."""
        if response.status_code == 204 or not response.content:
            return empty_factory()
        return response.json()

    async def get_projects(self) -> List[Dict[str, Any]]:
        """
        Get list of all projects with their branches

        Returns:
            List of projects with structure:
            [
                {
                    "project": {"id": "...", "name": "...", "time": "..."},
                    "branches": [{"id": "...", "name": "...", "time": "..."}]
                }
            ]
        """
        response = await self._request("GET", f"{self.base_url}/api/public/projects")
        return self._json_or_empty(response)

    async def get_snapshots(self, project_id: str, branch_id: str) -> List[Dict[str, Any]]:
        """
        Get list of snapshots for a project branch

        Args:
            project_id: Project UUID
            branch_id: Branch UUID

        Returns:
            List of snapshots
        """
        response = await self._request(
            "GET",
            f"{self.base_url}/api/public/projects/{project_id}/branch/{branch_id}/snapshots"
        )
        return self._json_or_empty(response)

    async def get_snapshots_flat(self, filter_base64: str) -> List[Dict[str, Any]]:
        """
        Get snapshots via flat endpoint: GET /api/public/snapshots?filters=<base64>

        Args:
            filter_base64: Base64-encoded JSON filter (project/branch + optional snapshot name)

        Returns:
            List of snapshots
        """
        url = f"{self.base_url}/api/public/snapshots"
        params = {"filters": filter_base64}
        response = await self._request("GET", url, params=params)
        return self._json_or_empty(response)

    async def get_warnings(
        self,
        project_id: str,
        branch_id: str,
        snapshot_id: str,
        filter_base64: str = None,
        traces: bool = False,
        checker_info: bool = False,
        review_history: bool = False,
        comment_history: bool = False,
        custom_filter: str = None,
    ) -> List[Dict[str, Any]]:
        """Fetch fullmarkers (warnings with details) for a snapshot."""
        url = (
            f"{self.base_url}/api/public/projects/{project_id}"
            f"/branch/{branch_id}/snapshots/{snapshot_id}/fullmarkers"
        )

        params = {}
        if filter_base64:
            params["filters"] = filter_base64
        params.update(self._optional_params(
            traces=traces, checker_info=checker_info,
            review_history=review_history, comment_history=comment_history,
            custom_filter=custom_filter,
        ))

        response = await self._request("GET", url, params=params)
        return self._json_or_empty(response)

    async def get_project_stats(
        self,
        project_id: str,
        branch_id: str,
        snapshot_id: str
    ) -> Dict[str, Any]:
        """
        Get statistics for a project snapshot
        """
        warnings = await self.get_warnings(project_id, branch_id, snapshot_id)

        stats = {
            "total_warnings": len(warnings),
            "by_severity": {},
            "by_review_status": {},
            "by_checker": {}
        }

        for warning in warnings:
            review = warning.get("review") or {}
            severity = review.get("severity") or "Unspecified"
            stats["by_severity"][severity] = stats["by_severity"].get(severity, 0) + 1

            status = review.get("status") or "Undecided"
            stats["by_review_status"][status] = stats["by_review_status"].get(status, 0) + 1

            checker = warning.get("warnClass") or "UNKNOWN"
            stats["by_checker"][checker] = stats["by_checker"].get(checker, 0) + 1

        return stats

    async def get_markers(
        self,
        project_id: str,
        branch_id: str,
        snapshot_id: str,
        filter_base64: Optional[str] = None,
        traces: bool = False,
        checker_info: bool = False,
        review_history: bool = False,
        comment_history: bool = False,
        custom_filter: str = None,
    ) -> List[Dict[str, Any]]:
        """Fetch markers (short form) via flat /api/public/markers."""
        url = f"{self.base_url}/api/public/markers"
        params = {}
        if filter_base64:
            params["filters"] = filter_base64
        params.update(self._optional_params(
            traces=traces, checker_info=checker_info,
            review_history=review_history, comment_history=comment_history,
            custom_filter=custom_filter,
        ))
        response = await self._request("GET", url, params=params)
        return self._json_or_empty(response)

    async def apply_advanced_filter(
        self,
        filter_expression: str,
        snapshot_ids: List[str],
    ) -> List[str]:
        """Evaluate a Svacer advanced-filter expression for one or more snapshots.

        This is the same endpoint used by the Svacer web UI.  The endpoint
        returns marker IDs; callers can then intersect them with marker data
        fetched through the public markers/fullmarkers endpoints.
        """
        url = f"{self.base_url}/api/public/afilters/apply"
        response = await self._request(
            "POST",
            url,
            json={"filter": filter_expression, "snapshot_id": snapshot_ids},
        )
        payload = self._json_or_empty(response, dict)
        marker_ids = payload.get("marker_ids") if isinstance(payload, dict) else None
        if (not isinstance(marker_ids, list) or
                any(not isinstance(marker_id, str) or not marker_id for marker_id in marker_ids)):
            raise SvacerAPIError("Advanced filter response has invalid marker_ids")
        return [str(marker_id) for marker_id in marker_ids if marker_id]

    async def export_markup(
        self,
        branch_id: str,
        snapshot_id: str,
        *,
        include_comments: bool = False,
    ) -> bytes:
        """Export newline-delimited JSON markup for one snapshot.

        ``export_all`` is intentional: besides existing reviews, Svacer then
        returns the invariant and locations for markers that are still
        Undecided.  Those server-produced records are the only safe base for a
        later import; marker locations are never guessed locally.
        """
        url = f"{self.base_url}/api/public/markup/export"
        response = await self._request(
            "POST",
            url,
            json={
                "source_id": branch_id,
                "skip_comments": not include_comments,
                "skip_review": False,
                "format": "json",
                "export_all": True,
                "compressed": False,
                "filters": [{"ids": [snapshot_id]}],
            },
        )
        if not response.content:
            raise SvacerAPIError("Markup export returned an empty response")
        return bytes(response.content)

    async def import_markup(
        self,
        branch_id: str,
        content: bytes,
        *,
        overwrite: str,
    ) -> bytes:
        """Import JSONL markup into a branch and return the raw result body."""
        if overwrite not in {"none", "force"}:
            raise ValueError("overwrite must be 'none' or 'force'")
        if not content:
            raise ValueError("markup content is empty")
        url = f"{self.base_url}/api/public/markup/import"
        response = await self._request(
            "POST",
            url,
            params={
                "target_id": branch_id,
                "format": "json",
                "overwrite": overwrite,
                "skip_comments": "false",
                "skip_review": "false",
                "response_with_result": "true",
                "compressed": "false",
            },
            files={
                "file": (
                    "svacer-import.jsonl",
                    content,
                    "application/x-ndjson",
                )
            },
        )
        if not response.content:
            raise SvacerAPIError("Markup import returned an empty response")
        return bytes(response.content)

    async def get_project_groups(self, name_or_id: str) -> Dict[str, Any]:
        """
        Get a project group by name or ID, with its full list of projects.

        Step 1: POST /api/public/admin/server/project-groups
                Body: {"action": "get", "project_group_name_or_id": "<name-or-uuid>"}
                → gets group ID and name

        Step 2: POST /api/public/admin/server/containers
                Body: {"action": "list", "type": "project", "parent": "<group_id>"}
                → gets all projects belonging to the group

        Args:
            name_or_id: Name or UUID of the project group

        Returns:
            Dict with project_group_id, project_group_name, and projects list
        """
        url_groups = f"{self.base_url}/api/public/admin/server/project-groups"
        group_response = await self._request("POST", url_groups, json={
            "action": "get",
            "project_group_name_or_id": name_or_id
        })
        group_data = self._json_or_empty(group_response, empty_factory=dict)

        group_id = group_data.get("project_group_id")
        group_name = group_data.get("project_group_name")

        projects = []
        if group_id:
            url_containers = f"{self.base_url}/api/public/admin/server/containers"
            containers_response = await self._request("POST", url_containers, json={
                "action": "list",
                "parent": group_id,
                "type": "project"
            })
            containers_data = self._json_or_empty(containers_response, empty_factory=dict)
            projects = containers_data.get("Containers") or containers_data.get("containers", [])

        return {
            "project_group_id": group_id,
            "project_group_name": group_name,
            "projects": projects
        }

    async def get_advanced_file_preview(
        self,
        snapshot_id: str,
        file_path: str,
        line: int = 1,
        before: int = 0,
        after: int = 99999
    ) -> Dict[str, Any]:
        """
        Get advanced file preview for a file in a snapshot.

        Uses flat endpoint: GET /api/public/advanced_file_preview?file=...&snapshot=...&line=...&before=...&after=...

        Args:
            snapshot_id: Snapshot UUID
            file_path: Path to the file in the snapshot
            line: Line number (required by API, default 1)
            before: Lines before (default 0)
            after: Lines after (default 99999 = whole file)

        Returns:
            Preview data (content, metadata, etc.)
        """
        url = f"{self.base_url}/api/public/advanced_file_preview"
        params = {
            "file": file_path,
            "snapshot": snapshot_id,
            "line": line,
            "before": before,
            "after": after,
            "output": "json",
        }
        response = await self._request("GET", url, params=params)
        return self._json_or_empty(response, empty_factory=dict)

    async def get_diff(
        self,
        base_snapshot_id: str,
        head_snapshot_id: Optional[str] = None,
        level: int = 0,
        checker_info: bool = False,
    ) -> Dict[str, Any]:
        """
        Get diff between two snapshots.

        Uses flat endpoint: GET /api/public/diff?snapshot_v1=...&snapshot_v2=...
        If head_snapshot_id is omitted, compares with the previous snapshot.

        Args:
            base_snapshot_id: Snapshot UUID (if head is omitted, compares with previous)
            head_snapshot_id: Optional newer snapshot UUID
            level: Detail level (0=stats, 1=stats+ids, >1=full)

        Returns:
            Diff data
        """
        url = f"{self.base_url}/api/public/diff"
        params = {
            "snapshot_v1": base_snapshot_id,
        }
        if head_snapshot_id:
            params["snapshot_v2"] = head_snapshot_id
        params["level"] = str(level)
        if checker_info:
            params["checker_info"] = "true"
        response = await self._request("GET", url, params=params)
        return self._json_or_empty(response, empty_factory=dict)

    async def aclose(self):
        """Close HTTP client if it was opened."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None
            self.auth._http_client = None
