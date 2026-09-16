from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from test_mcp_pipeline import ROOT, inventory, run_script


def prepare(tmp_path):
    inv = tmp_path / "inventory.json"
    dec = tmp_path / "decisions.jsonl"
    inv.write_text(json.dumps(inventory()), encoding="utf-8")
    result = run_script("make_mcp_decisions_template.py", "--inventory", str(inv), "--out", str(dec))
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in dec.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row.update(verdict="False Positive", confidence="high", source="fixture", control="guard",
                   sink="read", evidence=["Synthetic test, not a product finding"],
                   comment="FALSE POSITIVE\nSynthetic validation fixture.")
    return inv, dec, rows


def apply(inv, dec, result_file, *ids):
    return run_script("triage_queue.py", "--inventory", str(inv), "--decisions", str(dec),
                      "apply", "--results", str(result_file), "--allowed-ids", *ids)


@pytest.mark.parametrize("failure", ["duplicate", "missing", "extra", "metadata", "severity", "invalid", "corrupt_queue", "locked", "bad_json", "duplicate_assignment"])
def test_bad_apply_preserves_original(tmp_path, failure):
    inv, dec, rows = prepare(tmp_path)
    result_file = tmp_path / "worker.json"
    ids = ["m1", "m2"]
    if failure == "duplicate": rows.append(rows[0])
    if failure == "missing": rows.pop()
    if failure == "extra": rows[0]["marker_id"] = "alien"
    if failure == "metadata": rows[0]["line"] = 999
    if failure == "severity": rows[0]["severity"] = "Major"
    if failure == "invalid": rows[0]["verdict"] = "Probably fine"
    if failure == "duplicate_assignment": ids.append("m1")
    if failure == "locked": dec.with_name(dec.name + ".lock").touch()
    if failure == "corrupt_queue":
        pending = [json.loads(line) for line in dec.read_text(encoding="utf-8").splitlines()]
        pending[0]["file"] = "wrong.cc"
        dec.write_text("\n".join(json.dumps(row) for row in pending), encoding="utf-8")
    result_file.write_text("{" if failure == "bad_json" else json.dumps(rows), encoding="utf-8")
    before = dec.read_bytes()
    result = apply(inv, dec, result_file, *ids)
    assert result.returncode != 0
    assert dec.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("truncated", True), ("returned_count", 1), ("total_count", 3),
    ("filters_applied", {}),
    ("filters_applied", {**inventory()["filters_applied"], "severity": ["Critical"]}),
])
def test_incomplete_or_wrong_scope_rejected(tmp_path, field, value):
    data = inventory()
    data[field] = value
    inv = tmp_path / "inventory.json"
    dec = tmp_path / "decisions.jsonl"
    inv.write_text(json.dumps(data), encoding="utf-8")
    result = run_script("make_mcp_decisions_template.py", "--inventory", str(inv), "--out", str(dec))
    assert result.returncode != 0
    assert not dec.exists()


def test_repeated_apply_and_template_do_not_overwrite(tmp_path):
    inv, dec, rows = prepare(tmp_path)
    result_file = tmp_path / "worker.json"
    result_file.write_text(json.dumps(rows), encoding="utf-8")
    assert apply(inv, dec, result_file, "m1", "m2").returncode == 0
    before = dec.read_bytes()
    assert apply(inv, dec, result_file, "m1", "m2").returncode != 0
    assert run_script("make_mcp_decisions_template.py", "--inventory", str(inv), "--out", str(dec)).returncode != 0
    assert dec.read_bytes() == before


def test_concurrent_writers_do_not_lose_results(tmp_path):
    inv, dec, rows = prepare(tmp_path)
    files = [tmp_path / f"worker-{i}.json" for i in range(2)]
    for file, row in zip(files, rows): file.write_text(json.dumps([row]), encoding="utf-8")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply, inv, dec, files[i], rows[i]["marker_id"]) for i in range(2)]
        results = [future.result() for future in futures]
    # A rejected competing writer can retry. No success may silently disappear.
    saved = {r["marker_id"]: r for r in map(json.loads, dec.read_text(encoding="utf-8").splitlines())}
    for i, result in enumerate(results):
        if result.returncode == 0:
            assert saved[rows[i]["marker_id"]]["verdict"] == "False Positive"
        else:
            assert apply(inv, dec, files[i], rows[i]["marker_id"]).returncode == 0
    assert all(json.loads(line)["verdict"] == "False Positive" for line in dec.read_text(encoding="utf-8").splitlines())


def powershell(script, *args, cwd=None):
    return subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", str(script), *args], capture_output=True, timeout=60, cwd=cwd)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 portability test")
def test_portable_archive_in_cyrillic_directory(tmp_path):
    packed = powershell(ROOT / "make_portable_package.ps1")
    assert packed.returncode == 0, packed.stderr.decode(errors="replace")
    archive = max(
        (ROOT / "ARCHIVE").glob("svacer_gost_triage_portable_*.zip"),
        key=lambda p: p.stat().st_mtime_ns,
    )
    destination = tmp_path / "Другой пользователь с пробелами"
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        assert all(n.startswith("svacer_gost_triage/") and ".." not in n.split("/") for n in names)
        assert not any(part in {".venv", "jobs", ".git", ".env", "tests", "__pycache__"} for n in names for part in n.split("/"))
        z.extractall(destination)
    app = destination / "svacer_gost_triage"
    # Only our synthetic unrelated file is added, never any real credential file.
    (app / "private-notes.txt").write_text("DO NOT PACKAGE", encoding="utf-8")
    repacked = powershell(app / "make_portable_package.ps1", cwd=tmp_path)
    assert repacked.returncode == 0, repacked.stderr.decode(errors="replace")
    with zipfile.ZipFile(next((app / "ARCHIVE").glob("*.zip"))) as z:
        assert set(z.namelist()) == set(names)
    ids = ["11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "12345678-1234-1234-1234-123456789abc"]
    snapshot = "http://svacer01.sec.dev.rvision.local:8080/mode/review/project/" + ids[0] + "/branch/" + ids[1] + "/snapshot/" + ids[2]
    arguments = ["-SnapshotUrl", snapshot, "-RepositoryUrl", "https://example.invalid/project.git", "-GitRef", "v1.0", "-NoClipboard", "-NoOpen", "-NoDashboard"]
    for _ in range(2):
        result = subprocess.run([str(app / "new_triage_job.cmd"), *arguments],
                                input=b"\n", capture_output=True, timeout=30, cwd=tmp_path)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        jobs = list((app / "RESULTS").glob("*/job.json"))
    assert len(jobs) == 2
    for job_path in jobs:
        job = json.loads(job_path.read_text(encoding="utf-8-sig"))
        assert [job[k] for k in ("project_id", "branch_id", "snapshot_id")] == ids
        assert job["tool_directory"] == str(app)
        assert job["advanced_filter"] == inventory()["filters_applied"]["advanced_filter"]
        assert job["parallel_workers"] == 3 and job["batch_size"] == 15
        assert str(app) in (job_path.parent / "START_PROMPT.txt").read_text(encoding="utf-8-sig")
    result = powershell(app / "new_triage_job.ps1", *[a.replace("svacer01.sec.dev.rvision.local", "wrong.invalid") for a in arguments])
    assert result.returncode != 0
    assert len(list((app / "RESULTS").glob("*/job.json"))) == 2
    # Compile packaged Python sources; do not start a server or execute product code.
    for source in app.rglob("*.py"):
        compile(source.read_text(encoding="utf-8-sig"), str(source), "exec")
    # Exercise the queue from the unpacked bundle, not the original module path.
    inv, dec, rows = prepare(tmp_path)
    result_file = tmp_path / "packaged-worker.json"
    result_file.write_text(json.dumps(rows), encoding="utf-8")
    for script, args in [
        ("triage_queue.py", ["--inventory", str(inv), "--decisions", str(dec), "next", "--workers", "1"]),
        ("triage_queue.py", ["--inventory", str(inv), "--decisions", str(dec), "apply", "--results", str(result_file), "--allowed-ids", "m1", "m2"]),
        ("validate_mcp_decisions.py", ["--inventory", str(inv), "--decisions", str(dec)]),
        ("export_decisions_csv.py", ["--decisions", str(dec), "--out", str(tmp_path / "packaged.csv")]),
    ]:
        result = subprocess.run([sys.executable, str(app / script), *args], capture_output=True, timeout=30, cwd=tmp_path)
        assert result.returncode == 0, result.stderr.decode(errors="replace")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1")
def test_powershell_encoding_and_occupied_port(tmp_path):
    # Parse the actual scripts in Windows PowerShell, without running setup/auth.
    checker = tmp_path / "parse.ps1"
    checker.write_text("param([string]$Root)\n"
                       "if ($PSVersionTable.PSVersion.Major -ne 5) { throw 'Expected Windows PowerShell 5' }\n"
                       "Get-ChildItem -LiteralPath $Root -Filter '*.ps1' | ForEach-Object {\n"
                       "  $b = [IO.File]::ReadAllBytes($_.FullName)\n"
                       "  if (($b[0..2] -join ',') -ne '239,187,191') { throw ('Missing BOM: ' + $_.Name) }\n"
                       "  $tokens=$null; $parseErrors=$null\n"
                       "  $null = [Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$parseErrors)\n"
                       "  if ($parseErrors.Count) { throw ('Parse error: ' + $_.Name) }\n"
                       "}\n", encoding="utf-8-sig")
    checked = powershell(checker, "-Root", str(ROOT))
    assert checked.returncode == 0, checked.stderr.decode(errors="replace")
    wrapper = tmp_path / "occupied.ps1"
    wrapper.write_text("param([string]$Script)\n"
                       "function global:Get-NetTCPConnection { [pscustomobject]@{ State='Listen' } }\n"
                       "function global:Read-Host { return '' }\n"
                       "& $Script\nexit $LASTEXITCODE\n", encoding="utf-8-sig")
    checked = powershell(wrapper, "-Script", str(ROOT / "start_svacer_http.ps1"))
    assert checked.returncode == 3, checked.stderr.decode(errors="replace")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1")
def test_stop_analyze_pauses_all_local_jobs(tmp_path):
    tool = tmp_path / "tool"
    job = tool / "RESULTS" / "job-1"
    job.mkdir(parents=True)
    (job / "job.json").write_text("{}", encoding="utf-8")
    script = tool / "stop_components.ps1"
    script.write_bytes((ROOT / "stop_components.ps1").read_bytes())

    stopped = powershell(script, "-Mode", "Analyze")

    assert stopped.returncode == 0, stopped.stderr.decode(errors="replace")
    control = json.loads((job / "control.json").read_text(encoding="utf-8-sig"))
    assert control["pause_requested"] is True
    assert control["source"] == "STOP ANALYZE.cmd"
