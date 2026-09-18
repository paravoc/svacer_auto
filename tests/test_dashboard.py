from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from test_mcp_pipeline import inventory, inventory_with_existing_review, run_script
from triage_dashboard import collect_state, describe_exception, mcp_text, render, set_pause
from triage_gui import comment_without_heading, format_count, list_text, short_file


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_dashboard_reports_saved_work_and_current_assignment(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    inv = inventory()
    write_json(job / "markers.inventory.json", inv)
    decisions = []
    for index, marker in enumerate(inv["markers"]):
        decisions.append({
            "marker_id": marker["id"],
            "verdict": "False Positive" if index == 0 else None,
        })
    (job / "decisions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in decisions), encoding="utf-8"
    )
    note = [{"marker_id": inv["markers"][0]["id"], "verdict": "False Positive"}]
    write_json(job / "notes" / "batch-001-worker-1.json", note)
    write_json(job / "workers.status.json", {
        "state": "assigned",
        "batch": 2,
        "workers": [{"worker": 1, "status": "assigned", "assigned": 1, "saved": 0}],
    })

    state = collect_state(job)

    assert state["total"] == 2
    assert state["completed"] == 1 and state["pending"] == 1
    assert state["workers"][1]["saved"] == 1
    assert state["workers"][1]["assigned"] == 1
    assert "1/2" in render(state)


def test_dashboard_counts_only_markers_that_need_triage(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    inv = inventory_with_existing_review()
    write_json(job / "markers.inventory.json", inv)
    decisions = [
        {"marker_id": "m1", "verdict": None},
        {"marker_id": "m2", "verdict": None},
    ]
    (job / "decisions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in decisions), encoding="utf-8"
    )

    state = collect_state(job)

    assert state["inventory_total"] == 2
    assert state["already_reviewed"] == 1
    assert state["total"] == 1
    assert state["pending"] == 1
    assert "уже размечено 1 | для доразметки 1" in render(state)


def test_pause_file_stops_queue_before_new_batch(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    inv_path = job / "markers.inventory.json"
    decisions_path = job / "decisions.jsonl"
    write_json(inv_path, inventory())
    result = run_script(
        "make_mcp_decisions_template.py", "--inventory", str(inv_path), "--out", str(decisions_path)
    )
    assert result.returncode == 0
    set_pause(job, True)

    queued = run_script(
        "triage_queue.py", "--inventory", str(inv_path), "--decisions", str(decisions_path),
        "next", "--limit", "2", "--workers", "2",
    )
    assert queued.returncode == 0
    payload = json.loads(queued.stdout)
    assert payload["paused"] is True and payload["batch"] is None
    assert json.loads((job / "workers.status.json").read_text())["state"] == "paused"


def test_mcp_result_text_rejects_errors():
    ok = SimpleNamespace(isError=False, content=[SimpleNamespace(text='{"ok":true}')])
    assert json.loads(mcp_text(ok))["ok"] is True
    failed = SimpleNamespace(isError=True, content=[SimpleNamespace(text="denied")])
    try:
        mcp_text(failed)
    except RuntimeError as exc:
        assert "denied" in str(exc)
    else:
        raise AssertionError("MCP error was accepted")


def test_nested_taskgroup_error_shows_leaf_reason():
    nested = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [RuntimeError("Method not found: prepare_markup_import")],
    )
    message = describe_exception(nested)
    assert "Method not found: prepare_markup_import" in message
    assert "TaskGroup" not in message


def test_colored_render_has_status_colors_but_plain_render_does_not(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    state = collect_state(job)
    colored = render(state, use_color=True)
    plain = render(state, use_color=False)
    assert "\033[" in colored
    assert "\033[" not in plain


def test_dashboard_shows_confirmed_verification_and_token_estimate(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    inv = inventory()
    write_json(job / "markers.inventory.json", inv)
    decisions = [
        {
            "marker_id": "m1", "verdict": "Confirmed",
            "verification": {"status": "verified"},
        },
        {
            "marker_id": "m2", "verdict": "Confirmed",
            "verification": {
                "status": "challenged", "specific_issue": "reachable path is incomplete",
            },
        },
    ]
    (job / "decisions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in decisions), encoding="utf-8"
    )
    write_json(job / "notes" / "batch-001-worker-1.json", [decisions[0]])
    write_json(job / "notes" / "verify-batch-001-verifier-1.json", [{"marker_id": "m1"}])

    state = collect_state(job)
    output = render(state)

    assert state["verification"]["verified"] == 1
    assert state["verification"]["challenged"] == 1
    assert state["context"]["primary_calls"] == 1
    assert state["context"]["verifier_calls"] == 1
    assert "Проверка Confirmed: подтверждено 1/2" in output
    assert "Токены: ≈" in output


def test_gui_formats_large_counts_for_readability():
    assert format_count(514878) == "514 878"


def test_gui_marker_helpers_prepare_readable_details():
    assert short_file("/tmp/source/example.cc") == "example.cc"
    assert comment_without_heading("FALSE POSITIVE\nПуть недостижим.") == "Путь недостижим."
    assert comment_without_heading("Обычный комментарий") == "Обычный комментарий"
    assert list_text(["one", "two"]) == "• one\n• two"
