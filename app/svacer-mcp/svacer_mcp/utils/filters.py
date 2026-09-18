"""
Utilities for working with Svacer API filters
"""
import json
import base64
from typing import Dict, Any, List, Optional


class FilterBuilder:
    """Helper class to build and encode Svacer API filters"""

    def __init__(self):
        self.filter_dict = {}

    def with_review(self, statuses: List[str]) -> "FilterBuilder":
        self.filter_dict["review"] = statuses
        return self

    def with_checker(self, checkers: List[str]) -> "FilterBuilder":
        """Set checker filter. Accepts warnClass values (e.g. "DEREF_AFTER_NULL").

        Both /markers and fullmarkers endpoints use marker.checker in the filter body.
        Matches against the warnClass field in marker objects.
        This is the checker identifier, not the tool/analyzer name.
        """
        self.filter_dict["checker"] = checkers
        return self

    def with_file(self, paths: List[str]) -> "FilterBuilder":
        self.filter_dict["file"] = paths
        return self

    def build(self) -> str:
        """
        Build and encode the filter as base64 JSON (for fullmarkers endpoint).

        Swagger format for fullmarkers filters parameter:
        {
          "marker": {
            "file": "src/main.c",
            "checker": "DEREF_AFTER_NULL",
            "review": "Confirmed"
          }
        }
        Values are joined with "|" as regex alternatives.

        Returns:
            Base64-encoded JSON filter string, or empty string if no filters.
        """
        if not self.filter_dict:
            return ""

        marker_filter = {}
        if "file" in self.filter_dict:
            marker_filter["file"] = "|".join(self.filter_dict["file"])
        if "checker" in self.filter_dict:
            marker_filter["checker"] = "|".join(self.filter_dict["checker"])
        if "review" in self.filter_dict:
            marker_filter["review"] = "|".join(self.filter_dict["review"])

        api_filter = {"marker": marker_filter}
        json_str = json.dumps(api_filter, ensure_ascii=False)
        encoded = base64.b64encode(json_str.encode("utf-8")).decode("ascii")
        return encoded

    def build_markers_filter(
        self,
        project_id: str,
        branch_id: str,
        snapshot_id: str,
    ) -> str:
        """
        Build a base64-encoded JSON filter for the /api/public/markers endpoint.

        The format expected by Svacer:
        {
          "project": {"id": "<project_id>"},
          "branch": {"id": "<branch_id>"},
          "snapshot": {"id": "<snapshot_id>"},
          "marker": { ... optional marker-level filters ... }
        }

        Note: "checker" filter matches warnClass (e.g. "DEREF_AFTER_NULL"), not tool name.
        Note: "review" filter works server-side.

        Returns:
            Base64-encoded JSON string
        """
        filters = {
            "project": {"id": project_id},
            "branch": {"id": branch_id},
            "snapshot": {"id": snapshot_id},
        }

        marker_filter = {}
        if "file" in self.filter_dict:
            marker_filter["file"] = "|".join(self.filter_dict["file"])
        if "checker" in self.filter_dict:
            marker_filter["checker"] = "|".join(self.filter_dict["checker"])
        if "review" in self.filter_dict:
            marker_filter["review"] = "|".join(self.filter_dict["review"])

        if marker_filter:
            filters["marker"] = marker_filter

        json_str = json.dumps(filters, ensure_ascii=False)
        return base64.b64encode(json_str.encode("utf-8")).decode("ascii")

    def build_snapshots_filter(
        self,
        project_id: str,
        branch_id: str,
        name: Optional[str] = None,
    ) -> str:
        """
        Build base64-encoded JSON filter for /api/public/snapshots.

        Format:
        {
          "project": {"id": "<project_id>"},
          "branch": {"id": "<branch_id>"},
          "snapshot": {"name": "<name_pattern>"}  # optional
        }

        Returns:
            Base64-encoded JSON string
        """
        filters: Dict[str, Any] = {
            "project": {"id": project_id},
            "branch": {"id": branch_id},
        }
        if name:
            filters["snapshot"] = {"name": name}
        json_str = json.dumps(filters, ensure_ascii=False)
        return base64.b64encode(json_str.encode("utf-8")).decode("ascii")
