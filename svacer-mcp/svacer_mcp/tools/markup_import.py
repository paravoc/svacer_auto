"""Fail-closed preparation and import of completed ГОСТ triage decisions.

The public tools in this module deliberately split a remote write into two
calls.  ``prepare_markup_import`` is read-only with respect to Svacer and
creates a reviewable, fixed-path artifact.  ``apply_markup_import`` accepts
only that artifact, requires an exact confirmation phrase, records an attempt
before the network write, and verifies the result by exporting it back.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from ..api_client import SvacerAPIClient
from ..utils.filters import FilterBuilder
from ..utils.validators import validate_uuid


GOST_FILTER = 'filter(markers, "ГОСТ 71207-2024" in .checker_labels)'
VALID_VERDICTS = {"Confirmed", "False Positive", "Won't fix", "Unclear"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_SEVERITIES = {"Critical", "Major", "Minor"}
VALID_ACTIONS = {"Fix required", "Fix submitted", "Ignore"}
HEADINGS = {
    "Confirmed": "CONFIRMED",
    "False Positive": "FALSE POSITIVE",
    "Won't fix": "WONT FIX",
    "Unclear": "UNCLEAR",
}
MAX_MARKUP_BYTES = 256 * 1024 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _comment_for_import(comment: Any) -> str:
    """Remove the redundant verdict heading from the user-facing comment."""
    lines = str(comment or "").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip() in HEADINGS.values():
        lines.pop(0)
    return "\n".join(lines).strip()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"Required file is missing: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _read_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError as exc:
        raise ValueError(f"Required file is missing: {path.name}") from exc
    result: list[dict] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL in {path.name}, line {number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}, line {number}: expected a JSON object")
        result.append(value)
    return result


def _parse_markup(content: bytes, *, source: str) -> list[dict]:
    if not content:
        raise ValueError(f"{source} is empty")
    if len(content) > MAX_MARKUP_BYTES:
        raise ValueError(f"{source} is larger than {MAX_MARKUP_BYTES // (1024 * 1024)} MiB")
    if content.startswith(b"\x1f\x8b"):
        raise ValueError(f"{source} is gzip-compressed although uncompressed JSON was requested")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source} is not UTF-8 JSONL") from exc
    rows: list[dict] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON from {source}, line {number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{source}, line {number}: expected a JSON object")
        rows.append(value)
    if not rows:
        raise ValueError(f"{source} contains no markup records")
    return rows


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _atomic_json(path: Path, value: dict) -> None:
    content = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write(path, content)


@contextmanager
def _job_lock(job_directory: Path):
    lock_path = job_directory / ".svacer-import.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(
            f"Another import operation is using this job: {lock_path.name}. "
            "Do not run two coordinators for one job."
        ) from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _resolve_job_directory(value: str) -> tuple[Path, Path]:
    root_value = os.getenv("SVACER_TRIAGE_ROOT")
    if not root_value:
        raise ValueError("SVACER_TRIAGE_ROOT is not configured by the MCP launcher")
    try:
        root = Path(root_value).expanduser().resolve(strict=True)
        result_roots = [
            path.resolve(strict=True)
            for path in (root / "RESULTS", root / "jobs")
            if path.is_dir()
        ]
    except FileNotFoundError as exc:
        raise ValueError("The configured triage root or its RESULTS directory does not exist") from exc
    if not result_roots:
        raise ValueError("SVACER_TRIAGE_ROOT has no RESULTS directory")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("job_directory does not exist") from exc
    if not candidate.is_dir() or candidate.parent not in result_roots:
        raise ValueError("job_directory must be one direct child of SVACER_TRIAGE_ROOT\\RESULTS")
    return root, candidate


def _validate_job(job: dict, root: Path, job_directory: Path) -> None:
    for name in ("project_id", "branch_id", "snapshot_id"):
        value = job.get(name)
        if not isinstance(value, str):
            raise ValueError(f"job.json is missing {name}")
        validate_uuid(value, name)
    if job.get("advanced_filter") != GOST_FILTER:
        raise ValueError("job.json does not contain the exact ГОСТ 71207-2024 filter")
    if job.get("filter_name") != "ГОСТ 71207-2024":
        raise ValueError("job.json has an unexpected filter_name")
    recorded_job = job.get("job_directory")
    if recorded_job and Path(recorded_job).expanduser().resolve() != job_directory:
        recorded_path = Path(recorded_job).expanduser()
        migrated = (
            recorded_path.name == job_directory.name
            and recorded_path.parent.name in {"jobs", "RESULTS"}
            and job_directory.parent.name in {"jobs", "RESULTS"}
        )
        if not migrated:
            raise ValueError("job_directory does not match the path recorded in job.json")
    recorded_root = job.get("tool_directory")
    if recorded_root and Path(recorded_root).expanduser().resolve() != root:
        raise ValueError("tool_directory does not match SVACER_TRIAGE_ROOT")


def _validate_inventory(value: dict) -> tuple[list[dict], dict[str, dict]]:
    markers = value.get("markers")
    if not isinstance(markers, list) or any(not isinstance(item, dict) for item in markers):
        raise ValueError("markers.inventory.json has no valid markers array")
    if value.get("truncated") is not False:
        raise ValueError("Inventory does not prove truncated=false")
    for name in ("total_count", "returned_count"):
        if type(value.get(name)) is not int or value[name] != len(markers):
            raise ValueError("Inventory is incomplete; total/returned count does not match markers")
    filters = value.get("filters_applied")
    if not isinstance(filters, dict) or filters.get("advanced_filter") != GOST_FILTER:
        raise ValueError("Inventory does not prove the exact ГОСТ 71207-2024 filter")
    if any(filters.get(name) for name in ("severity", "review", "warnClass", "file", "custom_filter")):
        raise ValueError("Inventory has additional filters and is not the complete ГОСТ set")
    by_id: dict[str, dict] = {}
    for marker in markers:
        marker_id = str(marker.get("id") or "")
        if not marker_id or marker_id in by_id:
            raise ValueError("Inventory contains an empty or duplicate marker ID")
        by_id[marker_id] = marker
    return markers, by_id


def _validate_decisions(rows: list[dict], inventory: dict[str, dict]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    errors: list[str] = []
    for row in rows:
        marker_id = str(row.get("marker_id") or "")
        if not marker_id or marker_id in by_id:
            errors.append(f"empty or duplicate marker_id: {marker_id!r}")
            continue
        by_id[marker_id] = row
        marker = inventory.get(marker_id)
        if marker is None:
            errors.append(f"unknown marker_id: {marker_id}")
            continue
        for name in ("warnClass", "file", "line"):
            if row.get(name) != marker.get(name):
                errors.append(f"{marker_id}: {name} does not match the inventory")
        verdict = row.get("verdict")
        if verdict not in VALID_VERDICTS:
            errors.append(f"{marker_id}: incomplete or invalid verdict")
            continue
        if row.get("confidence") not in VALID_CONFIDENCE:
            errors.append(f"{marker_id}: invalid confidence")
        for name in ("source", "control", "sink"):
            if not isinstance(row.get(name), str) or not row[name].strip():
                errors.append(f"{marker_id}: empty {name}")
        for name in ("reachable_path", "evidence", "counterevidence", "proof_gaps"):
            if not isinstance(row.get(name), list):
                errors.append(f"{marker_id}: {name} must be an array")
        if isinstance(row.get("evidence"), list) and not row["evidence"]:
            errors.append(f"{marker_id}: evidence is empty")
        if not isinstance(row.get("boundary"), dict):
            errors.append(f"{marker_id}: boundary must be an object")
        comment = row.get("comment")
        nonempty = [line.strip() for line in str(comment or "").splitlines() if line.strip()]
        if not nonempty or nonempty[0] != HEADINGS[verdict] or len(nonempty) < 2:
            errors.append(f"{marker_id}: comment heading or evidence is invalid")
        if verdict == "Confirmed":
            if row.get("severity") not in VALID_SEVERITIES:
                errors.append(f"{marker_id}: Confirmed requires severity")
            if row.get("action") not in VALID_ACTIONS:
                errors.append(f"{marker_id}: Confirmed requires action")
        elif "severity" in row or "action" in row:
            errors.append(f"{marker_id}: {verdict} must not contain severity/action")
    missing = sorted(set(inventory) - set(by_id))
    extra = sorted(set(by_id) - set(inventory))
    if missing:
        errors.append(f"missing decisions: {missing[:10]}")
    if extra:
        errors.append(f"extra decisions: {extra[:10]}")
    if errors:
        raise ValueError("Decisions validation failed:\n- " + "\n- ".join(errors[:100]))
    return by_id


def _load_bundle(root: Path, job_directory: Path) -> tuple[dict, list[dict], dict[str, dict], dict[str, dict]]:
    job = _read_json(job_directory / "job.json")
    _validate_job(job, root, job_directory)
    inventory_value = _read_json(job_directory / "markers.inventory.json")
    markers, inventory = _validate_inventory(inventory_value)
    decisions = _validate_decisions(_read_jsonl(job_directory / "decisions.jsonl"), inventory)
    return job, markers, inventory, decisions


def _flatten_marker_response(value: Any) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("Svacer returned an invalid markers response")
    result: list[dict] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("markers"), list):
            raise ValueError("Svacer returned an invalid markers batch")
        if any(not isinstance(marker, dict) for marker in item["markers"]):
            raise ValueError("Svacer returned a non-object marker")
        result.extend(item["markers"])
    return result


async def _fresh_marker_invariants(
    api_client: SvacerAPIClient,
    job: dict,
    inventory: dict[str, dict],
) -> dict[str, str]:
    filtered_ids_list = await api_client.apply_advanced_filter(
        GOST_FILTER, [job["snapshot_id"]]
    )
    if len(filtered_ids_list) != len(set(filtered_ids_list)):
        raise ValueError("The advanced filter returned duplicate marker IDs")
    filtered_ids = set(filtered_ids_list)
    inventory_ids = set(inventory)
    if filtered_ids != inventory_ids:
        raise ValueError(
            "Fresh ГОСТ scope differs from markers.inventory.json: "
            f"missing={sorted(inventory_ids - filtered_ids)[:10]}, "
            f"new={sorted(filtered_ids - inventory_ids)[:10]}"
        )

    filter_b64 = FilterBuilder().build_markers_filter(
        job["project_id"], job["branch_id"], job["snapshot_id"]
    )
    short_rows = _flatten_marker_response(await api_client.get_markers(
        job["project_id"], job["branch_id"], job["snapshot_id"],
        filter_base64=filter_b64,
    ))
    by_id: dict[str, dict] = {}
    for marker in short_rows:
        marker_id = str(marker.get("id") or "")
        if marker_id not in filtered_ids:
            continue
        if not marker_id or marker_id in by_id:
            raise ValueError("Svacer returned an empty or duplicate marker ID")
        by_id[marker_id] = marker
    if set(by_id) != filtered_ids:
        raise ValueError(f"Svacer did not return all filtered marker records: {sorted(filtered_ids - set(by_id))[:10]}")

    missing_invariant = {marker_id for marker_id, marker in by_id.items() if not marker.get("invariant")}
    if missing_invariant:
        full_rows = await api_client.get_warnings(
            job["project_id"], job["branch_id"], job["snapshot_id"]
        )
        if not isinstance(full_rows, list) or any(not isinstance(item, dict) for item in full_rows):
            raise ValueError("Svacer returned an invalid fullmarkers response")
        for marker in full_rows:
            marker_id = str(marker.get("id") or "")
            if marker_id in missing_invariant and marker.get("invariant"):
                by_id[marker_id]["invariant"] = marker["invariant"]

    result: dict[str, str] = {}
    seen_invariants: dict[str, str] = {}
    for marker_id, marker in by_id.items():
        expected = inventory[marker_id]
        for name in ("warnClass", "file"):
            if marker.get(name) != expected.get(name):
                raise ValueError(f"Fresh marker {marker_id} changed {name}")
        if str(marker.get("line")) != str(expected.get("line")):
            raise ValueError(f"Fresh marker {marker_id} changed line")
        invariant = marker.get("invariant")
        if not isinstance(invariant, str) or not invariant:
            raise ValueError(
                f"Svacer did not return invariant for marker {marker_id}; "
                "safe import mapping is impossible"
            )
        if invariant in seen_invariants:
            raise ValueError(
                "Two ГОСТ markers in this snapshot share one invariant "
                f"({seen_invariants[invariant]}, {marker_id}); automatic import is ambiguous"
            )
        seen_invariants[invariant] = marker_id
        result[marker_id] = invariant
    return result


def _rows_by_invariant(rows: list[dict], needed: set[str], *, source: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in rows:
        invariant = row.get("invariant")
        if invariant not in needed:
            continue
        if invariant in result:
            raise ValueError(f"{source} contains duplicate invariant {invariant}")
        if not isinstance(row.get("locations"), list) or not row["locations"]:
            raise ValueError(f"{source} has no server locations for invariant {invariant}")
        result[invariant] = row
    missing = needed - set(result)
    if missing:
        raise ValueError(f"{source} has no rows for {len(missing)} required invariants")
    return result


def _review_tuple(review_data: Any) -> tuple[str, str, str]:
    review = review_data if isinstance(review_data, dict) else {}
    return (
        str(review.get("status") or "Undecided"),
        str(review.get("severity") or "Unspecified"),
        str(review.get("action") or "Undecided"),
    )


def _target_review(decision: dict) -> tuple[str, str, str]:
    if decision["verdict"] == "Confirmed":
        return decision["verdict"], decision["severity"], decision["action"]
    return decision["verdict"], "Unspecified", "Undecided"


def _deterministic_id(job: dict, marker_id: str, kind: str) -> str:
    material = f"svacer-gost-triage:{job['branch_id']}:{job['snapshot_id']}:{marker_id}:{kind}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, material))


def _build_import(
    job: dict,
    markers: list[dict],
    decisions: dict[str, dict],
    marker_invariants: dict[str, str],
    export_rows: dict[str, dict],
    author: str,
) -> tuple[bytes, list[dict[str, Any]]]:
    timestamp = _utc_now()
    output: list[bytes] = []
    differences: list[dict[str, Any]] = []
    for index, marker in enumerate(markers, 1):
        marker_id = str(marker["id"])
        decision = decisions[marker_id]
        invariant = marker_invariants[marker_id]
        exported = export_rows[invariant]
        target = _target_review(decision)
        current = _review_tuple(exported.get("review_data"))
        if current[0] != "Undecided" and current != target:
            differences.append({
                "marker_id": marker_id,
                "current": {"status": current[0], "severity": current[1], "action": current[2]},
                "target": {"status": target[0], "severity": target[1], "action": target[2]},
            })
        review_id = str(index)
        row = {
            "invariant": invariant,
            "review_data": {
                "status": target[0],
                "severity": target[1],
                "action": target[2],
                "origin_id": _deterministic_id(job, marker_id, "review"),
                "create_ts": timestamp,
                "created_by": author,
                "created_from": job["snapshot_id"],
            },
            "comments": [{
                "text": _comment_for_import(decision["comment"]),
                "format": "txt",
                "create_ts": timestamp,
                "createdBy": author,
                "origin_id": _deterministic_id(job, marker_id, "comment"),
                "review_id": review_id,
            }],
            "locations": exported["locations"],
            "id": review_id,
        }
        output.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    return b"".join(output), differences


def _parse_import_summary(content: bytes) -> dict:
    rows = _parse_markup(content, source="Svacer import response")
    summary = rows[0]
    required = {
        "total", "applied_reviews", "applied_comments", "skipped_reviews",
        "duplicate_reviews", "duplicate_comments",
    }
    if not required.issubset(summary) or any(type(summary[name]) is not int for name in required):
        raise ValueError("Svacer import response has no valid summary line")
    return {name: summary[name] for name in sorted(required)}


async def prepare_markup_import(
    job_directory: Annotated[str, Field(
        description="Absolute path to one completed job directory directly under SVACER_TRIAGE_ROOT/RESULTS"
    )],
    ctx: Context,
) -> str:
    """Prepare a Svacer JSONL import file without changing remote data.

    The tool validates the complete local decisions, re-evaluates the exact
    ГОСТ 71207-2024 filter, obtains current marker invariants and server-owned
    locations, and writes ``svacer-import.jsonl`` plus a preview.  It does not
    upload anything.  Use the exact confirmation phrase from its response with
    ``apply_markup_import`` only after a human reviews the preview.
    """
    api_client: SvacerAPIClient = ctx.request_context.lifespan_context["api_client"]
    root, job_path = _resolve_job_directory(job_directory)
    with _job_lock(job_path):
        attempt_path = job_path / "svacer-import-attempt.json"
        if attempt_path.exists():
            raise ValueError(
                "An import attempt is already recorded. Inspect its result and Svacer before any retry; "
                "automatic re-preparation is blocked to prevent duplicate comments."
            )
        job, markers, inventory, decisions = _load_bundle(root, job_path)
        marker_invariants = await _fresh_marker_invariants(api_client, job, inventory)
        exported_content = await api_client.export_markup(
            job["branch_id"], job["snapshot_id"], include_comments=False
        )
        exported_rows = _rows_by_invariant(
            _parse_markup(exported_content, source="Svacer markup export"),
            set(marker_invariants.values()),
            source="Svacer markup export",
        )
        import_content, differences = _build_import(
            job,
            markers,
            decisions,
            marker_invariants,
            exported_rows,
            author=api_client.auth.login,
        )
        digest = _sha256(import_content)
        import_path = job_path / "svacer-import.jsonl"
        preview_path = job_path / "svacer-import-preview.json"
        _atomic_write(import_path, import_content)
        counts = Counter(decision["verdict"] for decision in decisions.values())
        preview = {
            "schema_version": 1,
            "prepared_at": _utc_now(),
            "project_id": job["project_id"],
            "branch_id": job["branch_id"],
            "snapshot_id": job["snapshot_id"],
            "advanced_filter": GOST_FILTER,
            "marker_count": len(markers),
            "by_verdict": dict(sorted(counts.items())),
            "import_file": import_path.name,
            "sha256": digest,
            "inventory_sha256": _sha256((job_path / "markers.inventory.json").read_bytes()),
            "decisions_sha256": _sha256((job_path / "decisions.jsonl").read_bytes()),
            "marker_invariants": marker_invariants,
            "conflict_count": len(differences),
            "conflicts": differences,
            "requires_force": bool(differences),
            "confirmation": f"IMPORT {job['branch_id']} {digest[:12]}",
            "force_confirmation": f"FORCE IMPORT {job['branch_id']} {digest[:12]}",
        }
        _atomic_json(preview_path, preview)
        return json.dumps({
            "prepared": True,
            "remote_changed": False,
            "marker_count": len(markers),
            "by_verdict": dict(sorted(counts.items())),
            "conflict_count": len(differences),
            "requires_force": bool(differences),
            "import_file": str(import_path),
            "preview_file": str(preview_path),
            "confirmation": preview["confirmation"],
            "force_confirmation": preview["force_confirmation"],
        }, ensure_ascii=False, indent=2)


async def apply_markup_import(
    job_directory: Annotated[str, Field(
        description="Absolute path to the prepared job directory directly under SVACER_TRIAGE_ROOT/RESULTS"
    )],
    confirmation: Annotated[str, Field(
        description="Exact confirmation phrase returned by prepare_markup_import after human review"
    )],
    ctx: Context,
    overwrite: Annotated[str, Field(
        description="Conflict policy: none keeps existing non-empty review; force replaces it",
        pattern="^(none|force)$",
    )] = "none",
) -> str:
    """Upload prepared statuses and comments after an exact confirmation.

    This tool changes Svacer.  It accepts no arbitrary file path, refuses an
    already attempted job, records the attempt before sending, and exports the
    same snapshot after import to verify every status and comment.  It never
    retries an uncertain network outcome automatically.
    """
    api_client: SvacerAPIClient = ctx.request_context.lifespan_context["api_client"]
    root, job_path = _resolve_job_directory(job_directory)
    with _job_lock(job_path):
        attempt_path = job_path / "svacer-import-attempt.json"
        if attempt_path.exists():
            raise ValueError(
                "This job already has an import attempt. Inspect svacer-import-attempt.json, "
                "svacer-import-result.json and Svacer; automatic repeat is blocked."
            )
        job, markers, inventory, decisions = _load_bundle(root, job_path)
        preview = _read_json(job_path / "svacer-import-preview.json")
        import_path = job_path / "svacer-import.jsonl"
        try:
            import_content = import_path.read_bytes()
        except FileNotFoundError as exc:
            raise ValueError("svacer-import.jsonl is missing; run prepare_markup_import") from exc
        digest = _sha256(import_content)
        if digest != preview.get("sha256"):
            raise ValueError("svacer-import.jsonl changed after preparation")
        if preview.get("inventory_sha256") != _sha256((job_path / "markers.inventory.json").read_bytes()):
            raise ValueError("markers.inventory.json changed after preparation")
        if preview.get("decisions_sha256") != _sha256((job_path / "decisions.jsonl").read_bytes()):
            raise ValueError("decisions.jsonl changed after preparation")
        for name in ("project_id", "branch_id", "snapshot_id"):
            if preview.get(name) != job[name]:
                raise ValueError(f"Preview {name} does not match job.json")
        if preview.get("advanced_filter") != GOST_FILTER or preview.get("marker_count") != len(markers):
            raise ValueError("Preview scope is invalid")
        expected_confirmation = (
            preview.get("force_confirmation") if overwrite == "force" else preview.get("confirmation")
        )
        if confirmation != expected_confirmation:
            raise ValueError("Confirmation phrase does not match the prepared file, branch, and overwrite mode")
        if preview.get("requires_force") and overwrite != "force":
            raise ValueError(
                "Existing non-empty reviews differ from the prepared decisions. "
                "Review conflicts and use the FORCE confirmation only if replacement is intended."
            )
        marker_invariants = await _fresh_marker_invariants(api_client, job, inventory)
        if marker_invariants != preview.get("marker_invariants"):
            raise ValueError("Fresh marker-to-invariant mapping differs from the prepared preview")

        attempt = {
            "schema_version": 1,
            "status": "started",
            "started_at": _utc_now(),
            "branch_id": job["branch_id"],
            "snapshot_id": job["snapshot_id"],
            "sha256": digest,
            "overwrite": overwrite,
            "marker_count": len(markers),
        }
        _atomic_json(attempt_path, attempt)
        try:
            response_content = await api_client.import_markup(
                job["branch_id"], import_content, overwrite=overwrite
            )
            summary = _parse_import_summary(response_content)
        except Exception as exc:
            attempt.update(status="outcome_unknown", finished_at=_utc_now(), error=type(exc).__name__)
            _atomic_json(attempt_path, attempt)
            raise ValueError(
                "Svacer import did not return a verified result. The outcome may be unknown; "
                "inspect Svacer before any manual retry."
            ) from exc

        _atomic_write(job_path / "svacer-import-result.jsonl", response_content)
        _atomic_json(job_path / "svacer-import-result.json", summary)

        verification: dict[str, Any]
        try:
            readback_content = await api_client.export_markup(
                job["branch_id"], job["snapshot_id"], include_comments=True
            )
            readback = _rows_by_invariant(
                _parse_markup(readback_content, source="Svacer read-back export"),
                set(marker_invariants.values()),
                source="Svacer read-back export",
            )
            status_mismatches: list[str] = []
            comment_mismatches: list[str] = []
            for marker in markers:
                marker_id = str(marker["id"])
                decision = decisions[marker_id]
                row = readback[marker_invariants[marker_id]]
                if _review_tuple(row.get("review_data")) != _target_review(decision):
                    status_mismatches.append(marker_id)
                comments = row.get("comments") if isinstance(row.get("comments"), list) else []
                expected_comment = _comment_for_import(decision["comment"])
                if not any(isinstance(item, dict) and item.get("text") == expected_comment for item in comments):
                    comment_mismatches.append(marker_id)
            verification = {
                "verified": not status_mismatches and not comment_mismatches,
                "status_mismatches": status_mismatches,
                "comment_mismatches": comment_mismatches,
                "checked": len(markers),
            }
        except Exception as exc:
            verification = {
                "verified": False,
                "checked": 0,
                "readback_error": type(exc).__name__,
            }
        _atomic_json(job_path / "svacer-import-readback.json", verification)
        attempt.update(
            status="completed_verified" if verification["verified"] else "completed_unverified",
            finished_at=_utc_now(),
            summary=summary,
            verification=verification,
        )
        _atomic_json(attempt_path, attempt)
        return json.dumps({
            "remote_changed": True,
            "status": attempt["status"],
            "summary": summary,
            "verification": verification,
            "result_file": str(job_path / "svacer-import-result.json"),
            "readback_file": str(job_path / "svacer-import-readback.json"),
        }, ensure_ascii=False, indent=2)
