from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from svacer_mcp.api_client import SvacerAPIClient
from svacer_mcp.tools.markup_import import (
    GOST_FILTER,
    apply_markup_import,
    prepare_markup_import,
)
from svacer_mcp.tools.warnings import _format_warning


IDS = {
    "project": "11111111-2222-3333-4444-555555555555",
    "branch": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "snapshot": "12345678-1234-1234-1234-123456789abc",
}


def decision(marker_id: str, line: int, verdict: str) -> dict:
    row = {
        "marker_id": marker_id,
        "warnClass": "TEST_WARNING",
        "file": "/src/test.cc",
        "line": line,
        "verdict": verdict,
        "confidence": "high",
        "source": "fixture source",
        "control": "fixture control",
        "sink": "fixture sink",
        "reachable_path": ["fixture path"],
        "boundary": {"product_surface": "fixture"},
        "evidence": ["fixture evidence"],
        "counterevidence": [],
        "proof_gaps": [],
        "comment": {
            "Confirmed": "CONFIRMED\nFixture confirmed.",
            "False Positive": "FALSE POSITIVE\nFixture is unreachable.",
        }[verdict],
    }
    if verdict == "Confirmed":
        row.update(severity="Major", action="Fix required")
    return row


def make_job(tmp_path: Path, *, conflict: bool = False):
    root = tmp_path / "tool"
    job = root / "jobs" / "job-1"
    job.mkdir(parents=True)
    job_value = {
        "project_id": IDS["project"],
        "branch_id": IDS["branch"],
        "snapshot_id": IDS["snapshot"],
        "filter_name": "ГОСТ 71207-2024",
        "advanced_filter": GOST_FILTER,
        "tool_directory": str(root),
        "job_directory": str(job),
    }
    markers = [
        {"id": "m1", "warnClass": "TEST_WARNING", "file": "/src/test.cc", "line": 10},
        {"id": "m2", "warnClass": "TEST_WARNING", "file": "/src/test.cc", "line": 20},
    ]
    inventory = {
        "total_count": 2,
        "returned_count": 2,
        "truncated": False,
        "filters_applied": {
            "advanced_filter": GOST_FILTER,
            "severity": None,
            "review": None,
            "warnClass": None,
            "file": None,
            "custom_filter": None,
        },
        "markers": markers,
    }
    rows = [decision("m1", 10, "Confirmed"), decision("m2", 20, "False Positive")]
    (job / "job.json").write_text(json.dumps(job_value), encoding="utf-8")
    (job / "markers.inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    (job / "decisions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    current_m1 = {
        "status": "False Positive", "severity": "Unspecified", "action": "Undecided"
    } if conflict else {
        "status": "Undecided", "severity": "Unspecified", "action": "Undecided"
    }
    export_rows = [
        {
            "invariant": "inv-1",
            "review_data": current_m1,
            "locations": [{"warnClass": "TEST_WARNING", "file": "/src/test.cc", "line": 10}],
            "id": "1",
        },
        {
            "invariant": "inv-2",
            "review_data": {"status": "Undecided", "severity": "Unspecified", "action": "Undecided"},
            "locations": [{"warnClass": "TEST_WARNING", "file": "/src/test.cc", "line": 20}],
            "id": "2",
        },
    ]
    return root, job, export_rows


class FakeAPI:
    def __init__(self, export_rows, *, missing_invariant=False):
        self.export_rows = export_rows
        self.missing_invariant = missing_invariant
        self.auth = SimpleNamespace(login="test-user")
        self.import_calls = []
        self.imported_rows = None

    async def apply_advanced_filter(self, expression, snapshot_ids):
        assert expression == GOST_FILTER
        assert snapshot_ids == [IDS["snapshot"]]
        return ["m1", "m2"]

    async def get_markers(self, project_id, branch_id, snapshot_id, **kwargs):
        rows = []
        for marker_id, invariant, line in (("m1", "inv-1", 10), ("m2", "inv-2", 20)):
            rows.append({
                "id": marker_id,
                "invariant": None if self.missing_invariant else invariant,
                "warnClass": "TEST_WARNING",
                "file": "/src/test.cc",
                "line": line,
            })
        return [{"markers": rows}]

    async def get_warnings(self, project_id, branch_id, snapshot_id, **kwargs):
        return []

    async def export_markup(self, branch_id, snapshot_id, *, include_comments=False):
        rows = self.imported_rows if include_comments and self.imported_rows is not None else self.export_rows
        return "".join(json.dumps(row) + "\n" for row in rows).encode()

    async def import_markup(self, branch_id, content, *, overwrite):
        self.import_calls.append((branch_id, overwrite, content))
        self.imported_rows = [json.loads(line) for line in content.decode().splitlines()]
        count = len(self.imported_rows)
        return (json.dumps({
            "total": count,
            "applied_reviews": count,
            "applied_comments": count,
            "skipped_reviews": 0,
            "duplicate_reviews": 0,
            "duplicate_comments": 0,
        }) + "\n").encode()


def context(api):
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context={"api_client": api})
    )


@pytest.mark.asyncio
async def test_prepare_is_read_only_and_builds_statuses_comments(monkeypatch, tmp_path):
    root, job, export_rows = make_job(tmp_path)
    monkeypatch.setenv("SVACER_TRIAGE_ROOT", str(root))
    api = FakeAPI(export_rows)

    result = json.loads(await prepare_markup_import(str(job), context(api)))

    assert result["remote_changed"] is False
    assert result["marker_count"] == 2
    assert not api.import_calls
    rows = [json.loads(line) for line in (job / "svacer-import.jsonl").read_text().splitlines()]
    assert rows[0]["review_data"]["status"] == "Confirmed"
    assert rows[0]["review_data"]["severity"] == "Major"
    assert rows[1]["review_data"] == {
        **rows[1]["review_data"],
        "status": "False Positive",
        "severity": "Unspecified",
        "action": "Undecided",
    }
    assert rows[0]["review_data"]["created_by"] == "test-user"
    assert rows[1]["comments"][0]["createdBy"] == "test-user"
    assert rows[1]["comments"][0]["text"] == "Fixture is unreachable."
    assert rows[0]["locations"] == export_rows[0]["locations"]


@pytest.mark.asyncio
async def test_prepare_imports_only_undecided_inventory_markers(monkeypatch, tmp_path):
    root, job, export_rows = make_job(tmp_path)
    inventory = json.loads((job / "markers.inventory.json").read_text())
    inventory["markers"][0]["review"] = {
        "status": "False Positive",
        "severity": "Unspecified",
        "action": "Undecided",
    }
    inventory["markers"][1]["review"] = None
    (job / "markers.inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    monkeypatch.setenv("SVACER_TRIAGE_ROOT", str(root))
    api = FakeAPI(export_rows)

    prepared = json.loads(await prepare_markup_import(str(job), context(api)))

    assert prepared["inventory_marker_count"] == 2
    assert prepared["already_reviewed_count"] == 1
    assert prepared["marker_count"] == 1
    rows = [json.loads(line) for line in (job / "svacer-import.jsonl").read_text().splitlines()]
    assert [row["invariant"] for row in rows] == ["inv-2"]

    applied = json.loads(await apply_markup_import(
        str(job), prepared["confirmation"], context(api), overwrite="none"
    ))
    assert applied["status"] == "completed_verified"
    assert applied["verification"]["checked"] == 1


@pytest.mark.asyncio
async def test_conflict_requires_force_then_imports_and_verifies(monkeypatch, tmp_path):
    root, job, export_rows = make_job(tmp_path, conflict=True)
    monkeypatch.setenv("SVACER_TRIAGE_ROOT", str(root))
    api = FakeAPI(export_rows)
    prepared = json.loads(await prepare_markup_import(str(job), context(api)))
    assert prepared["requires_force"] is True
    assert prepared["conflict_count"] == 1

    with pytest.raises(ValueError, match="Existing non-empty reviews"):
        await apply_markup_import(
            str(job), prepared["confirmation"], context(api), overwrite="none"
        )
    assert not api.import_calls

    applied = json.loads(await apply_markup_import(
        str(job), prepared["force_confirmation"], context(api), overwrite="force"
    ))
    assert applied["status"] == "completed_verified"
    assert applied["verification"]["verified"] is True
    assert len(api.import_calls) == 1
    assert (job / "svacer-import-attempt.json").exists()
    assert (job / "svacer-import-result.json").exists()
    assert (job / "svacer-import-readback.json").exists()

    with pytest.raises(ValueError, match="already has an import attempt"):
        await apply_markup_import(
            str(job), prepared["force_confirmation"], context(api), overwrite="force"
        )
    assert len(api.import_calls) == 1


@pytest.mark.asyncio
async def test_bad_confirmation_and_tamper_never_upload(monkeypatch, tmp_path):
    root, job, export_rows = make_job(tmp_path)
    monkeypatch.setenv("SVACER_TRIAGE_ROOT", str(root))
    api = FakeAPI(export_rows)
    prepared = json.loads(await prepare_markup_import(str(job), context(api)))
    with pytest.raises(ValueError, match="Confirmation phrase"):
        await apply_markup_import(str(job), "yes", context(api), overwrite="none")
    (job / "svacer-import.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after preparation"):
        await apply_markup_import(
            str(job), prepared["confirmation"], context(api), overwrite="none"
        )
    assert not api.import_calls


@pytest.mark.asyncio
async def test_missing_invariant_and_outside_path_fail_closed(monkeypatch, tmp_path):
    root, job, export_rows = make_job(tmp_path)
    monkeypatch.setenv("SVACER_TRIAGE_ROOT", str(root))
    api = FakeAPI(export_rows, missing_invariant=True)
    with pytest.raises(ValueError, match="safe import mapping is impossible"):
        await prepare_markup_import(str(job), context(api))

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="direct child"):
        await prepare_markup_import(str(outside), context(api))
    assert not api.import_calls


def api_client():
    client = SvacerAPIClient.__new__(SvacerAPIClient)
    client.auth = MagicMock(url="http://svacer", timeout=10)
    client.base_url = "http://svacer"
    client.timeout = 10
    return client


@pytest.mark.asyncio
async def test_api_export_payload_is_snapshot_scoped_and_uncompressed():
    client = api_client()
    response = MagicMock(content=b'{"invariant":"i"}\n')
    request = AsyncMock(return_value=response)
    with patch.object(client, "_request", new=request):
        result = await client.export_markup(IDS["branch"], IDS["snapshot"], include_comments=True)
    assert result == response.content
    request.assert_awaited_once_with(
        "POST", "http://svacer/api/public/markup/export",
        json={
            "source_id": IDS["branch"],
            "skip_comments": False,
            "skip_review": False,
            "format": "json",
            "export_all": True,
            "compressed": False,
            "filters": [{"ids": [IDS["snapshot"]]}],
        },
    )


@pytest.mark.asyncio
async def test_api_import_has_explicit_policy_and_multipart_file():
    client = api_client()
    response = MagicMock(content=b'{"total":1}\n')
    request = AsyncMock(return_value=response)
    content = b'{"invariant":"i"}\n'
    with patch.object(client, "_request", new=request):
        result = await client.import_markup(IDS["branch"], content, overwrite="none")
    assert result == response.content
    request.assert_awaited_once_with(
        "POST", "http://svacer/api/public/markup/import",
        params={
            "target_id": IDS["branch"],
            "format": "json",
            "overwrite": "none",
            "skip_comments": "false",
            "skip_review": "false",
            "response_with_result": "true",
            "compressed": "false",
        },
        files={"file": ("svacer-import.jsonl", content, "application/x-ndjson")},
    )
    with pytest.raises(ValueError, match="overwrite"):
        await client.import_markup(IDS["branch"], content, overwrite="last")


def test_marker_formatter_preserves_invariant_for_exact_import_mapping():
    assert _format_warning({"id": "m1", "invariant": "inv-1"})["invariant"] == "inv-1"
