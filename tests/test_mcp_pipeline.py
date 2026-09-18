from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(APP / name), *args],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def inventory() -> dict:
    return {
        "total_count": 2,
        "returned_count": 2,
        "truncated": False,
        "filters_applied": {"advanced_filter": 'filter(markers, "ГОСТ 71207-2024" in .checker_labels)'},
        "markers": [
            {"id": "m1", "warnClass": "A", "file": "a.cc", "line": 10},
            {"id": "m2", "warnClass": "B", "file": "b.cc", "line": 20},
        ],
    }


def inventory_with_existing_review() -> dict:
    value = inventory()
    value["markers"][0]["review"] = {
        "status": "False Positive",
        "severity": "Unspecified",
        "action": "Undecided",
    }
    value["markers"][1]["review"] = None
    return value


def test_existing_svacer_review_is_skipped_automatically(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    decisions_path = tmp_path / "decisions.jsonl"
    inventory_path.write_text(json.dumps(inventory_with_existing_review()), encoding="utf-8")

    created = run_script(
        "make_mcp_decisions_template.py",
        "--inventory", str(inventory_path),
        "--out", str(decisions_path),
    )
    assert created.returncode == 0, created.stderr
    rows = [json.loads(line) for line in decisions_path.read_text().splitlines()]
    assert [row["marker_id"] for row in rows] == ["m2"]
    assert "Уже размечено в Svacer: 1" in created.stdout
    assert "Для доразметки: 1" in created.stdout

    queued = run_script(
        "triage_queue.py",
        "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
        "next", "--limit", "15", "--workers", "3",
    )
    assert queued.returncode == 0, queued.stderr
    payload = json.loads(queued.stdout)
    assert payload["progress"] == {
        "inventory_total": 2,
        "already_reviewed": 1,
        "total": 1,
        "completed": 0,
        "pending": 1,
        "by_verdict": {
            "Confirmed": 0,
            "False Positive": 0,
            "Unclear": 0,
            "Won't fix": 0,
        },
        "verification": {
            "required": 0,
            "verified": 0,
            "pending": 0,
            "challenged": 0,
            "import_ready": True,
        },
    }
    assert payload["batch"]["marker_ids"] == ["m2"]


def test_legacy_full_template_skips_previously_reviewed_rows(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    decisions_path = tmp_path / "decisions.jsonl"
    inventory_path.write_text(json.dumps(inventory_with_existing_review()), encoding="utf-8")
    legacy_inventory = inventory()
    legacy_path = tmp_path / "legacy-inventory.json"
    legacy_path.write_text(json.dumps(legacy_inventory), encoding="utf-8")
    created = run_script(
        "make_mcp_decisions_template.py",
        "--inventory", str(legacy_path),
        "--out", str(decisions_path),
    )
    assert created.returncode == 0

    queued = run_script(
        "triage_queue.py",
        "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
        "next", "--limit", "15",
    )
    assert queued.returncode == 0, queued.stderr
    payload = json.loads(queued.stdout)
    assert payload["progress"]["total"] == 1
    assert payload["progress"]["already_reviewed"] == 1
    assert payload["batch"]["marker_ids"] == ["m2"]


def test_template_validation_and_csv(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    decisions_path = tmp_path / "decisions.jsonl"
    csv_path = tmp_path / "decisions.csv"
    inventory_path.write_text(json.dumps(inventory(), ensure_ascii=False), encoding="utf-8")

    created = run_script(
        "make_mcp_decisions_template.py",
        "--inventory", str(inventory_path),
        "--out", str(decisions_path),
    )
    assert created.returncode == 0, created.stderr
    rows = [json.loads(line) for line in decisions_path.read_text(encoding="utf-8").splitlines()]
    rows[0].update(
        verdict="Confirmed",
        confidence="high",
        entrypoint="request handler",
        source="input",
        control="none",
        sink="dereference",
        build_reachability="target is linked",
        product_reachability="request reaches caller",
        reachable_path=["caller -> sink"],
        impact="process crash",
        boundary={
            "product_surface": "request handler",
            "source_trust": "remote client",
            "boundary_crossed": True,
            "policy_basis": "request must not terminate process",
        },
        evidence=["a.cc:10"],
        comment="CONFIRMED\nПуть подтверждён.",
        severity="Major",
        action="Fix required",
        verification={
            "status": "verified",
            "verifier_id": "verifier-1",
            "reason": "Путь независимо подтверждён.",
            "evidence": ["a.cc:10"],
            "rechecked_paths": ["a.cc"],
            "verified_at": "2026-01-01T00:00:00Z",
        },
    )
    rows[1].update(
        verdict="False Positive",
        confidence="high",
        entrypoint="constructor",
        source="constructor",
        control="guard",
        sink="read",
        build_reachability="target is linked",
        product_reachability="guard prevents the reported state",
        reachable_path=[],
        impact="none because the read is unreachable",
        boundary={
            "product_surface": "internal object",
            "source_trust": "trusted constructor",
            "boundary_crossed": False,
            "policy_basis": "read requires initialized object",
        },
        evidence=["b.cc:20"],
        counterevidence=["b.cc:19 guard dominates read"],
        comment="FALSE POSITIVE\nЧтение возможно только после записи.",
    )
    decisions_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    checked = run_script(
        "validate_mcp_decisions.py",
        "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr

    exported = run_script(
        "export_decisions_csv.py",
        "--decisions", str(decisions_path),
        "--out", str(csv_path),
    )
    assert exported.returncode == 0, exported.stderr
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert [row["marker_id"] for row in csv_rows] == ["m1", "m2"]


def test_validator_rejects_extra_fields_for_false_positive(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    decisions_path = tmp_path / "decisions.jsonl"
    inventory_data = inventory()
    inventory_data["total_count"] = 1
    inventory_data["returned_count"] = 1
    inventory_data["markers"] = inventory_data["markers"][:1]
    inventory_path.write_text(json.dumps(inventory_data), encoding="utf-8")
    decision = {
        "marker_id": "m1",
        "warnClass": "A",
        "file": "a.cc",
        "line": 10,
        "verdict": "False Positive",
        "confidence": "high",
        "source": "input",
        "control": "guard",
        "sink": "read",
        "reachable_path": [],
        "evidence": ["a.cc:10"],
        "counterevidence": [],
        "proof_gaps": [],
        "comment": "FALSE POSITIVE\nОпасное состояние недостижимо.",
        "severity": "Major",
    }
    decisions_path.write_text(json.dumps(decision, ensure_ascii=False) + "\n", encoding="utf-8")
    checked = run_script(
        "validate_mcp_decisions.py",
        "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
    )
    assert checked.returncode == 2
    assert "severity/action должны отсутствовать" in checked.stdout


def test_queue_next_progress_and_reopen(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    decisions_path = tmp_path / "decisions.jsonl"
    inventory_path.write_text(json.dumps(inventory()), encoding="utf-8")
    created = run_script(
        "make_mcp_decisions_template.py",
        "--inventory", str(inventory_path),
        "--out", str(decisions_path),
    )
    assert created.returncode == 0

    next_result = run_script(
        "triage_queue.py",
        "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
        "next", "--limit", "15",
    )
    assert next_result.returncode == 0, next_result.stderr
    next_payload = json.loads(next_result.stdout)
    assert next_payload["progress"]["pending"] == 2
    assert next_payload["batch"]["marker_ids"] == ["m1", "m2"]
    assert next_payload["batch"]["worker_count"] == 1

    records = [json.loads(line) for line in decisions_path.read_text().splitlines()]
    records[0]["verdict"] = "Unclear"
    records[0]["confidence"] = "low"
    records[0]["source"] = "input"
    records[0]["control"] = "unknown"
    records[0]["sink"] = "read"
    records[0]["evidence"] = ["a.cc:10"]
    records[0]["comment"] = "UNCLEAR\nНужен точный caller."
    decisions_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
        encoding="utf-8",
    )

    progress = run_script(
        "triage_queue.py",
        "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
        "progress",
    )
    assert progress.returncode == 0
    assert json.loads(progress.stdout)["completed"] == 1

    reopened = run_script(
        "triage_queue.py",
        "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
        "reopen", "--ids", "m1",
    )
    assert reopened.returncode == 0
    assert json.loads(reopened.stdout)["reopened"] == ["m1"]
    final_records = [json.loads(line) for line in decisions_path.read_text().splitlines()]
    assert final_records[0]["verdict"] is None
    assert final_records[0]["comment"] == ""


def test_parallel_queue_and_atomic_worker_apply(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    decisions_path = tmp_path / "decisions.jsonl"
    worker_1_path = tmp_path / "worker-1.json"
    worker_2_path = tmp_path / "worker-2.json"
    (tmp_path / "job.json").write_text(
        json.dumps({"run_mode": "single_batch"}), encoding="utf-8"
    )
    inventory_path.write_text(json.dumps(inventory()), encoding="utf-8")
    created = run_script(
        "make_mcp_decisions_template.py",
        "--inventory", str(inventory_path),
        "--out", str(decisions_path),
    )
    assert created.returncode == 0

    queued = run_script(
        "triage_queue.py",
        "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
        "next", "--limit", "15", "--workers", "3",
    )
    assert queued.returncode == 0, queued.stderr
    batch = json.loads(queued.stdout)["batch"]
    assert batch["worker_count"] == 2
    assigned = [marker_id for item in batch["assignments"] for marker_id in item["marker_ids"]]
    assert set(assigned) == {"m1", "m2"}

    records = [json.loads(line) for line in decisions_path.read_text().splitlines()]
    for record in records:
        record.update(
            verdict="False Positive",
            confidence="high",
            entrypoint="caller",
            source="input",
            control="guard",
            sink="read",
            build_reachability="target is linked",
            product_reachability="guard rejects the dangerous state",
            reachable_path=["caller -> guard -> sink"],
            impact="none because the dangerous state is unreachable",
            boundary={
                "product_surface": "test surface",
                "source_trust": "caller input",
                "boundary_crossed": False,
                "policy_basis": "guard dominates sink",
            },
            evidence=[f'{record["file"]}:{record["line"]}'],
            counterevidence=[f'{record["file"]}:{record["line"]} guard'],
            proof_gaps=[],
            comment="FALSE POSITIVE\nОпасное состояние недостижимо.",
        )
    worker_1_path.write_text(json.dumps([records[0]], ensure_ascii=False), encoding="utf-8")
    worker_2_path.write_text(json.dumps([records[1]], ensure_ascii=False), encoding="utf-8")

    applied = run_script(
        "triage_queue.py",
        "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
        "apply", "--results", str(worker_1_path), str(worker_2_path),
        "--allowed-ids", "m1", "m2",
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert json.loads(applied.stdout)["paused_after_batch"] is True
    saved = [json.loads(line) for line in decisions_path.read_text().splitlines()]
    assert [item["verdict"] for item in saved] == ["False Positive", "False Positive"]
    paused = run_script(
        "triage_queue.py", "--inventory", str(inventory_path),
        "--decisions", str(decisions_path), "next", "--limit", "1", "--workers", "1",
    )
    assert paused.returncode == 0
    assert json.loads(paused.stdout)["paused"] is True
    verification = run_script(
        "triage_queue.py", "--inventory", str(inventory_path),
        "--decisions", str(decisions_path), "verify-next", "--limit", "1", "--workers", "1",
    )
    assert verification.returncode == 0
    assert "paused" not in json.loads(verification.stdout)


def test_confirmed_requires_independent_verification(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    decisions_path = tmp_path / "decisions.jsonl"
    analyst_path = tmp_path / "analyst.json"
    verifier_path = tmp_path / "verify-batch-001-verifier-1.json"
    inventory_data = inventory()
    inventory_data["total_count"] = inventory_data["returned_count"] = 1
    inventory_data["markers"] = inventory_data["markers"][:1]
    inventory_path.write_text(json.dumps(inventory_data), encoding="utf-8")
    assert run_script(
        "make_mcp_decisions_template.py", "--inventory", str(inventory_path),
        "--out", str(decisions_path),
    ).returncode == 0
    row = json.loads(decisions_path.read_text())
    row.update(
        verdict="Confirmed", confidence="high", entrypoint="request",
        source="input", control="none", sink="dereference",
        build_reachability="linked target", product_reachability="request reaches sink",
        reachable_path=["request -> sink"], impact="process crash",
        boundary={
            "product_surface": "request", "source_trust": "remote",
            "boundary_crossed": True, "policy_basis": "availability",
        },
        evidence=["a.cc:10"], counterevidence=[], proof_gaps=[],
        comment="CONFIRMED\nПуть подтверждён.", severity="Major", action="Fix required",
    )
    analyst_path.write_text(json.dumps([row], ensure_ascii=False), encoding="utf-8")
    applied = run_script(
        "triage_queue.py", "--inventory", str(inventory_path), "--decisions", str(decisions_path),
        "apply", "--results", str(analyst_path), "--allowed-ids", "m1",
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr
    saved = json.loads(decisions_path.read_text())
    assert saved["verification"]["status"] == "pending"
    blocked = run_script(
        "validate_mcp_decisions.py", "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
    )
    assert blocked.returncode == 2
    assert "не прошёл независимую проверку" in blocked.stdout

    verify_queue = run_script(
        "triage_queue.py", "--inventory", str(inventory_path), "--decisions", str(decisions_path),
        "verify-next", "--limit", "5", "--workers", "2",
    )
    assignment = json.loads(verify_queue.stdout)["batch"]
    assert assignment["marker_ids"] == ["m1"]
    verifier_path.write_text(json.dumps([{
        "marker_id": "m1",
        "decision": "verified",
        "verifier_id": "verifier-1",
        "reason": "Проверены вход, путь и аварийное завершение.",
        "evidence": ["a.cc:10 dereferences the unchecked value"],
        "rechecked_paths": ["a.cc"],
    }], ensure_ascii=False), encoding="utf-8")
    verified = run_script(
        "triage_queue.py", "--inventory", str(inventory_path), "--decisions", str(decisions_path),
        "verify-apply", "--results", str(verifier_path), "--allowed-ids", "m1",
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    checked = run_script(
        "validate_mcp_decisions.py", "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_vague_verifier_challenge_is_rejected(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    decisions_path = tmp_path / "decisions.jsonl"
    result_path = tmp_path / "verify-batch-001-verifier-1.json"
    inventory_data = inventory()
    inventory_data["total_count"] = inventory_data["returned_count"] = 1
    inventory_data["markers"] = inventory_data["markers"][:1]
    inventory_path.write_text(json.dumps(inventory_data), encoding="utf-8")
    decision = {
        "marker_id": "m1", "warnClass": "A", "file": "a.cc", "line": 10,
        "verdict": "Confirmed", "verification": {"status": "pending"},
    }
    decisions_path.write_text(json.dumps(decision) + "\n", encoding="utf-8")
    result_path.write_text(json.dumps([{
        "marker_id": "m1", "decision": "challenged", "verifier_id": "verifier-1",
        "reason": "Есть сомнение", "evidence": [], "rechecked_paths": [],
    }], ensure_ascii=False), encoding="utf-8")
    result = run_script(
        "triage_queue.py", "--inventory", str(inventory_path), "--decisions", str(decisions_path),
        "verify-apply", "--results", str(result_path), "--allowed-ids", "m1",
    )
    assert result.returncode != 0
    assert "challenge_type" in result.stderr or "evidence" in result.stderr


def test_concrete_verifier_challenge_blocks_import_until_reanalysis(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    decisions_path = tmp_path / "decisions.jsonl"
    analyst_path = tmp_path / "analyst.json"
    verifier_path = tmp_path / "verify-batch-001-verifier-1.json"
    inventory_data = inventory()
    inventory_data["total_count"] = inventory_data["returned_count"] = 1
    inventory_data["markers"] = inventory_data["markers"][:1]
    inventory_path.write_text(json.dumps(inventory_data), encoding="utf-8")
    assert run_script(
        "make_mcp_decisions_template.py", "--inventory", str(inventory_path),
        "--out", str(decisions_path),
    ).returncode == 0

    row = json.loads(decisions_path.read_text())
    row.update(
        verdict="Confirmed", confidence="high", entrypoint="request",
        source="input", control="none", sink="dereference",
        build_reachability="linked target", product_reachability="request reaches sink",
        reachable_path=["request -> sink"], impact="process crash",
        boundary={
            "product_surface": "request", "source_trust": "remote",
            "boundary_crossed": True, "policy_basis": "availability",
        },
        evidence=["a.cc:10"], counterevidence=[], proof_gaps=[],
        comment="CONFIRMED\nПуть подтверждён.", severity="Major", action="Fix required",
    )
    analyst_path.write_text(json.dumps([row], ensure_ascii=False), encoding="utf-8")
    assert run_script(
        "triage_queue.py", "--inventory", str(inventory_path), "--decisions", str(decisions_path),
        "apply", "--results", str(analyst_path), "--allowed-ids", "m1",
    ).returncode == 0

    verifier_path.write_text(json.dumps([{
        "marker_id": "m1",
        "decision": "challenged",
        "verifier_id": "verifier-1",
        "reason": "Проверка сборки показала, что файл не входит в целевой binary.",
        "evidence": ["BUILD:42 excludes a.cc from envoy target"],
        "rechecked_paths": ["BUILD", "a.cc"],
        "challenge_type": "build_reachability_gap",
        "specific_issue": "В основном решении неверно указана достижимость в сборке.",
        "resolution_needed": "Повторно проверить BUILD target и переразметить маркер.",
        "recommended_verdict": "False Positive",
    }], ensure_ascii=False), encoding="utf-8")
    challenged = run_script(
        "triage_queue.py", "--inventory", str(inventory_path), "--decisions", str(decisions_path),
        "verify-apply", "--results", str(verifier_path), "--allowed-ids", "m1",
    )
    assert challenged.returncode == 0, challenged.stdout + challenged.stderr
    saved = json.loads(decisions_path.read_text())
    assert saved["verification"]["status"] == "challenged"
    assert saved["verification"]["challenge_type"] == "build_reachability_gap"

    blocked = run_script(
        "validate_mcp_decisions.py", "--inventory", str(inventory_path),
        "--decisions", str(decisions_path),
    )
    assert blocked.returncode == 2
    assert "не прошёл независимую проверку" in blocked.stdout

    reopened = run_script(
        "triage_queue.py", "--inventory", str(inventory_path), "--decisions", str(decisions_path),
        "reopen", "--ids", "m1",
    )
    assert reopened.returncode == 0, reopened.stdout + reopened.stderr
    reset = json.loads(decisions_path.read_text())
    assert reset["verdict"] is None
    assert reset["verification"]["status"] == "not_required"
