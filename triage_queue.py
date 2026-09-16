#!/usr/bin/env python3
"""Small persistent work queue for Svacer MCP triage.

The decisions JSONL is the state store: verdict=null means pending. This keeps
resume semantics transparent and avoids another MCP server or database.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


VALID_VERDICTS = {"Confirmed", "False Positive", "Won't fix", "Unclear"}
GOST_FILTER = 'filter(markers, "ГОСТ 71207-2024" in .checker_labels)'
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_SEVERITIES = {"Critical", "Major", "Minor"}
VALID_ACTIONS = {"Fix required", "Fix submitted", "Ignore"}
HEADINGS = {
    "Confirmed": "CONFIRMED",
    "False Positive": "FALSE POSITIVE",
    "Won't fix": "WONT FIX",
    "Unclear": "UNCLEAR",
}
WORKER_NOTE_RE = re.compile(r"^batch-(\d+)-worker-(\d+)\.json$", re.IGNORECASE)


def load_inventory(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(value, str):
        value = json.loads(value)
    markers = value.get("markers") if isinstance(value, dict) else None
    if not isinstance(markers, list):
        raise SystemExit("Некорректный inventory.json: отсутствует массив markers")
    if value.get("truncated") is not False:
        raise SystemExit("Инвентарь не подтверждает truncated=false")
    if any(type(value.get(key)) is not int or value[key] != len(markers)
           for key in ("total_count", "returned_count")):
        raise SystemExit("Инвентарь обрезан; повтори get_markers с limit=0")
    filters = value.get("filters_applied")
    if not isinstance(filters, dict) or filters.get("advanced_filter") != GOST_FILTER:
        raise SystemExit("Инвентарь не подтверждает точный фильтр ГОСТ 71207-2024")
    if any(filters.get(key) for key in ("severity", "review", "warnClass", "file", "custom_filter")):
        raise SystemExit("Инвентарь должен содержать весь ГОСТ без дополнительных фильтров")
    if any(not isinstance(marker, dict) for marker in markers):
        raise SystemExit("Некорректный элемент markers")
    ids = [str(marker.get("id") or "") for marker in markers]
    if any(not marker_id for marker_id in ids) or len(set(ids)) != len(ids):
        raise SystemExit("Пустые или повторяющиеся marker id в inventory.json")
    return markers


def load_decisions(path: Path) -> list[dict]:
    result = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Ошибка JSONL, строка {number}: {exc}") from exc
            if not isinstance(item, dict):
                raise SystemExit(f"Строка {number}: ожидался JSON-объект")
            result.append(item)
    return result


def marker_review_status(marker: dict) -> str:
    """Return the current Svacer review status from a compact marker row."""
    review = marker.get("review")
    if review is None:
        return "Undecided"
    if isinstance(review, dict):
        status = review.get("status")
    elif isinstance(review, str):
        status = review
    else:
        raise SystemExit("Некорректное поле review в inventory.json")
    normalized = str(status or "").strip()
    if not normalized or normalized.casefold() == "undecided":
        return "Undecided"
    return normalized


def markers_for_triage(inventory: list[dict]) -> list[dict]:
    """Select only markers that had no review when the inventory was saved."""
    return [marker for marker in inventory if marker_review_status(marker) == "Undecided"]


def state(inventory: list[dict], decisions: list[dict]) -> tuple[dict[str, dict], Counter]:
    by_id = {str(item.get("marker_id") or ""): item for item in decisions}
    if "" in by_id or len(by_id) != len(decisions):
        raise SystemExit("Пустые или повторяющиеся marker_id в decisions.jsonl")
    inventory_by_id = {str(marker["id"]): marker for marker in inventory}
    inventory_ids = set(inventory_by_id)
    triage_ids = {str(marker["id"]) for marker in markers_for_triage(inventory)}
    if not triage_ids.issubset(by_id) or not set(by_id).issubset(inventory_ids):
        missing = sorted(triage_ids - set(by_id))
        extra = sorted(set(by_id) - inventory_ids)
        raise SystemExit(f"decisions.jsonl не совпадает с inventory: missing={missing[:5]}, extra={extra[:5]}")
    counts = Counter()
    for decision in decisions:
        marker_id = str(decision["marker_id"])
        marker = inventory_by_id[marker_id]
        if any(decision.get(key) != marker.get(key) for key in ("warnClass", "file", "line")):
            raise SystemExit("Метаданные решения не совпадают с инвентарём")
        if marker_id not in triage_ids:
            continue
        verdict = decision.get("verdict")
        if verdict is not None and (not isinstance(verdict, str) or verdict not in VALID_VERDICTS):
            raise SystemExit("Недопустимый verdict в очереди; запись не считается Pending")
        counts[verdict if verdict in VALID_VERDICTS else "Pending"] += 1
    return by_id, counts


def progress_payload(inventory: list[dict], decisions: list[dict]) -> dict:
    _, counts = state(inventory, decisions)
    triage_total = len(markers_for_triage(inventory))
    pending = counts.get("Pending", 0)
    return {
        "inventory_total": len(inventory),
        "already_reviewed": len(inventory) - triage_total,
        "total": triage_total,
        "completed": triage_total - pending,
        "pending": pending,
        "by_verdict": {name: counts.get(name, 0) for name in sorted(VALID_VERDICTS)},
    }


def next_parallel_batch(
    inventory: list[dict], decisions: list[dict], limit: int, workers: int
) -> dict:
    by_id, _ = state(inventory, decisions)
    pending = [
        marker
        for marker in markers_for_triage(inventory)
        if by_id[str(marker["id"])].get("verdict") not in VALID_VERDICTS
    ]
    payload = progress_payload(inventory, decisions)
    if not pending:
        return {"progress": payload, "batch": None}

    selected = pending[:limit]
    grouped: OrderedDict[tuple[object, object], list[dict]] = OrderedDict()
    for marker in selected:
        key = (marker.get("warnClass"), marker.get("file"))
        grouped.setdefault(key, []).append(marker)

    chunks = [
        {"key": key, "markers": markers}
        for key, markers in grouped.items()
    ]
    target_workers = min(workers, len(selected))
    while len(chunks) < target_workers:
        splittable = [chunk for chunk in chunks if len(chunk["markers"]) > 1]
        if not splittable:
            break
        largest = max(splittable, key=lambda chunk: len(chunk["markers"]))
        chunks.remove(largest)
        midpoint = (len(largest["markers"]) + 1) // 2
        chunks.append({"key": largest["key"], "markers": largest["markers"][:midpoint]})
        chunks.append({"key": largest["key"], "markers": largest["markers"][midpoint:]})

    assignments = [
        {"worker": number + 1, "count": 0, "groups": [], "marker_ids": [], "markers": []}
        for number in range(target_workers)
    ]
    for chunk in sorted(chunks, key=lambda item: len(item["markers"]), reverse=True):
        assignment = min(assignments, key=lambda item: (item["count"], item["worker"]))
        warn_class, file_name = chunk["key"]
        compact = [
            {
                "id": marker.get("id"),
                "warnClass": marker.get("warnClass"),
                "file": marker.get("file"),
                "line": marker.get("line"),
                "msg": marker.get("msg"),
                "function": marker.get("function"),
                "review": marker.get("review"),
            }
            for marker in chunk["markers"]
        ]
        marker_ids = [str(marker["id"]) for marker in compact]
        assignment["groups"].append(
            {
                "warnClass": warn_class,
                "file": file_name,
                "marker_ids": marker_ids,
            }
        )
        assignment["marker_ids"].extend(marker_ids)
        assignment["markers"].extend(compact)
        assignment["count"] += len(compact)

    trace_groups = [
        {
            "warnClass": key[0],
            "file": key[1],
            "marker_ids": [str(marker["id"]) for marker in markers],
        }
        for key, markers in grouped.items()
    ]
    return {
        "progress": payload,
        "batch": {
            "count": len(selected),
            "worker_count": len(assignments),
            "marker_ids": [str(marker["id"]) for marker in selected],
            "trace_groups": trace_groups,
            "assignments": assignments,
        },
    }


def atomic_write_jsonl(path: Path, records: list[dict]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def pause_requested(decisions_path: Path) -> bool:
    control_path = decisions_path.parent / "control.json"
    if not control_path.exists():
        return False
    try:
        value = json.loads(control_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Некорректный control.json: {exc}") from exc
    if not isinstance(value, dict) or type(value.get("pause_requested", False)) is not bool:
        raise SystemExit("Некорректный control.json: pause_requested должен быть bool")
    return value.get("pause_requested", False)


def next_batch_number(job_directory: Path) -> int:
    maximum = 0
    notes = job_directory / "notes"
    if notes.is_dir():
        for path in notes.iterdir():
            match = WORKER_NOTE_RE.match(path.name)
            if match:
                maximum = max(maximum, int(match.group(1)))
    status_path = job_directory / "workers.status.json"
    if status_path.exists():
        try:
            current = json.loads(status_path.read_text(encoding="utf-8-sig"))
            if isinstance(current, dict) and type(current.get("batch")) is int:
                maximum = max(maximum, current["batch"])
        except (OSError, json.JSONDecodeError):
            pass
    return maximum + 1


def record_assignments(decisions_path: Path, batch: dict | None, *, paused: bool = False) -> None:
    status_path = decisions_path.parent / "workers.status.json"
    if paused:
        value = {
            "state": "paused",
            "updated_at": utc_now(),
            "batch": None,
            "workers": [],
        }
    elif batch is None:
        value = {
            "state": "complete",
            "updated_at": utc_now(),
            "batch": None,
            "workers": [],
        }
    else:
        value = {
            "state": "assigned",
            "updated_at": utc_now(),
            "batch": next_batch_number(decisions_path.parent),
            "workers": [
                {
                    "worker": assignment["worker"],
                    "status": "assigned",
                    "assigned": assignment["count"],
                    "saved": 0,
                    "marker_ids": assignment["marker_ids"],
                }
                for assignment in batch["assignments"]
            ],
        }
    atomic_write_json(status_path, value)


def record_saved_workers(decisions_path: Path, result_paths: list[Path]) -> None:
    status_path = decisions_path.parent / "workers.status.json"
    if not status_path.exists():
        return
    try:
        value = json.loads(status_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(value, dict) or not isinstance(value.get("workers"), list):
        return
    saved_by_worker: Counter[int] = Counter()
    for path in result_paths:
        match = WORKER_NOTE_RE.match(path.name)
        if not match:
            continue
        try:
            saved_by_worker[int(match.group(2))] += len(load_worker_results([path]))
        except SystemExit:
            continue
    for worker in value["workers"]:
        if not isinstance(worker, dict) or type(worker.get("worker")) is not int:
            continue
        number = worker["worker"]
        worker["saved"] = saved_by_worker.get(number, 0)
        if worker["saved"] >= int(worker.get("assigned") or 0):
            worker["status"] = "saved"
    value["state"] = "saved"
    value["updated_at"] = utc_now()
    atomic_write_json(status_path, value)


@contextmanager
def decision_lock(path: Path):
    """Fail closed on competing writers. A crash leaves a visible stale lock."""
    lock_path = path.with_name(path.name + ".lock")
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SystemExit(f"Очередь занята: {lock_path}. Не запускай два координатора на один job.") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock_path.unlink()


def load_worker_results(paths: list[Path]) -> list[dict]:
    results: list[dict] = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise SystemExit(f"Файл результата не найден: {path}") from exc
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Некорректный JSON в {path}: {exc}") from exc
        if isinstance(value, dict):
            value = value.get("decisions")
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise SystemExit(f"{path}: ожидался JSON-массив решений")
        results.extend(value)
    return results


def validate_worker_result(result: dict, current: dict) -> list[str]:
    marker_id = str(result.get("marker_id") or "")
    errors: list[str] = []
    for name in ("warnClass", "file", "line"):
        if result.get(name) != current.get(name):
            errors.append(f"{marker_id}: поле {name} не совпадает с очередью")
    verdict = result.get("verdict")
    if not isinstance(verdict, str) or verdict not in VALID_VERDICTS:
        errors.append(f"{marker_id}: недопустимый verdict {verdict!r}")
        return errors
    if result.get("confidence") not in VALID_CONFIDENCE:
        errors.append(f"{marker_id}: некорректный confidence")
    for name in ("source", "control", "sink"):
        if not isinstance(result.get(name), str) or not result[name].strip():
            errors.append(f"{marker_id}: поле {name} пустое")
    for name in ("reachable_path", "evidence", "counterevidence", "proof_gaps"):
        if not isinstance(result.get(name), list):
            errors.append(f"{marker_id}: поле {name} должно быть массивом")
    if isinstance(result.get("evidence"), list) and not result["evidence"]:
        errors.append(f"{marker_id}: evidence пустое")
    if not isinstance(result.get("boundary"), dict):
        errors.append(f"{marker_id}: boundary должен быть объектом")
    comment = str(result.get("comment") or "")
    nonempty = [line.strip() for line in comment.splitlines() if line.strip()]
    if not nonempty or nonempty[0] != HEADINGS[verdict]:
        errors.append(f"{marker_id}: неверный заголовок комментария")
    elif len(nonempty) < 2:
        errors.append(f"{marker_id}: отсутствует доказательство в комментарии")
    if verdict == "Confirmed":
        if result.get("severity") not in VALID_SEVERITIES:
            errors.append(f"{marker_id}: для Confirmed нужна severity")
        if result.get("action") not in VALID_ACTIONS:
            errors.append(f"{marker_id}: для Confirmed нужен action")
    elif "severity" in result or "action" in result:
        errors.append(f"{marker_id}: для {verdict} severity/action должны отсутствовать")
    return errors


def apply_worker_results(
    decisions: list[dict], result_paths: list[Path], allowed_ids: list[str], path: Path,
    triage_ids: set[str],
) -> dict:
    results = load_worker_results(result_paths)
    requested = set(allowed_ids)
    if not requested or len(requested) != len(allowed_ids):
        raise SystemExit("Назначение пустое либо содержит повторяющиеся ID")
    result_ids = [str(item.get("marker_id") or "") for item in results]
    if "" in result_ids or len(result_ids) != len(set(result_ids)):
        raise SystemExit("В результатах подагентов есть пустые или повторяющиеся marker_id")
    if set(result_ids) != requested:
        missing = sorted(requested - set(result_ids))
        extra = sorted(set(result_ids) - requested)
        raise SystemExit(f"Результаты не совпадают с назначением: missing={missing}, extra={extra}")

    by_id = {str(item.get("marker_id")): item for item in decisions}
    unknown = sorted(requested - set(by_id))
    if unknown:
        raise SystemExit(f"Неизвестные marker_id: {unknown}")
    excluded = sorted(requested - triage_ids)
    if excluded:
        raise SystemExit(f"Маркеры уже размечены в Svacer и исключены из доразметки: {excluded}")
    errors: list[str] = []
    for result in results:
        marker_id = str(result["marker_id"])
        current = by_id[marker_id]
        if current.get("verdict") in VALID_VERDICTS:
            errors.append(f"{marker_id}: решение уже заполнено")
            continue
        errors.extend(validate_worker_result(result, current))
    if errors:
        raise SystemExit("Ошибки результатов:\n- " + "\n- ".join(errors))

    result_by_id = {str(item["marker_id"]): item for item in results}
    merged = [result_by_id.get(str(item["marker_id"]), item) for item in decisions]
    atomic_write_jsonl(path, merged)
    return {"applied": sorted(result_by_id), "count": len(result_by_id)}


def reopen(decisions: list[dict], ids: list[str], path: Path, triage_ids: set[str]) -> dict:
    requested = set(ids)
    known = {str(item.get("marker_id")) for item in decisions}
    unknown = sorted(requested - known)
    if unknown:
        raise SystemExit(f"Неизвестные marker_id: {unknown}")
    excluded = sorted(requested - triage_ids)
    if excluded:
        raise SystemExit(f"Маркеры уже размечены в Svacer и не входят в локальную очередь: {excluded}")
    for item in decisions:
        if str(item.get("marker_id")) not in requested:
            continue
        item["verdict"] = None
        item["confidence"] = None
        item["source"] = ""
        item["control"] = ""
        item["sink"] = ""
        item["reachable_path"] = []
        item["evidence"] = []
        item["counterevidence"] = []
        item["proof_gaps"] = []
        item["comment"] = ""
        item.pop("severity", None)
        item.pop("action", None)
    atomic_write_jsonl(path, decisions)
    return {"reopened": sorted(requested), "count": len(requested)}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Очередь локальной разметки Svacer")
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--decisions", required=True)
    subparsers = parser.add_subparsers(dest="action", required=True)
    next_parser = subparsers.add_parser("next")
    next_parser.add_argument("--limit", type=int, default=15)
    next_parser.add_argument("--workers", type=int, default=1)
    subparsers.add_parser("progress")
    reopen_parser = subparsers.add_parser("reopen")
    reopen_parser.add_argument("--ids", nargs="+", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--results", nargs="+", required=True)
    apply_parser.add_argument("--allowed-ids", nargs="+", required=True)
    args = parser.parse_args()

    inventory_path = Path(args.inventory).expanduser().resolve()
    decisions_path = Path(args.decisions).expanduser().resolve()
    inventory = load_inventory(inventory_path)
    decisions = load_decisions(decisions_path)

    if args.action == "next":
        if args.limit < 1 or args.limit > 50:
            raise SystemExit("--limit должен быть от 1 до 50")
        if args.workers < 1 or args.workers > 8:
            raise SystemExit("--workers должен быть от 1 до 8")
        if pause_requested(decisions_path):
            result = {"progress": progress_payload(inventory, decisions), "paused": True, "batch": None}
            record_assignments(decisions_path, None, paused=True)
        else:
            result = next_parallel_batch(inventory, decisions, args.limit, args.workers)
            record_assignments(decisions_path, result.get("batch"))
    elif args.action == "progress":
        result = progress_payload(inventory, decisions)
    else:
        with decision_lock(decisions_path):
            # Reload only after obtaining the lock: another process may have saved
            # results since the initial read. Never overwrite with a stale copy.
            decisions = load_decisions(decisions_path)
            state(inventory, decisions)
            triage_ids = {str(marker["id"]) for marker in markers_for_triage(inventory)}
            if args.action == "apply":
                result_paths = [Path(name).expanduser().resolve() for name in args.results]
                result = apply_worker_results(
                    decisions,
                    result_paths,
                    args.allowed_ids,
                    decisions_path,
                    triage_ids,
                )
                record_saved_workers(decisions_path, result_paths)
            else:
                result = reopen(decisions, args.ids, decisions_path, triage_ids)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
