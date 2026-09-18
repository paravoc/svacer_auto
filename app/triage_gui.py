#!/usr/bin/env python3
"""Graphical dashboard for the local Svacer GOST triage workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable

from triage_dashboard import (
    call_mcp_tool,
    check_mcp,
    collect_state,
    friendly_mcp_error,
    read_json,
    resolve_job,
    set_pause,
    start_svacer_reconnect,
)


BG = "#111820"
PANEL = "#1b2632"
TEXT = "#e6edf3"
MUTED = "#9aa7b2"
BLUE = "#36a3ff"
GREEN = "#35c46a"
YELLOW = "#f2bd3d"
RED = "#ff5d67"


def format_count(value: int) -> str:
    return f"{value:,}".replace(",", " ")


class TriageGui:
    def __init__(self, root: tk.Tk, job: Path, app_directory: Path) -> None:
        self.root = root
        self.job = job
        self.app_directory = app_directory
        self.settings = read_json(app_directory / "svacer-settings.json")
        self.mcp_url = str(self.settings.get("mcp_url") or "http://127.0.0.1:8002/mcp")
        self.token = os.getenv("SVACER_LOCAL_MCP_TOKEN", "")
        self.busy = False
        self.closed = False
        self.refresh_after_id: str | None = None

        job_data = read_json(job / "job.json") if (job / "job.json").exists() else {}
        repository = str(job_data.get("repository_url") or "").rstrip("/").rsplit("/", 1)[-1]
        if repository.endswith(".git"):
            repository = repository[:-4]
        git_ref = str(job_data.get("git_ref") or "")
        self.target_name = " ".join(part for part in (repository, git_ref) if part) or job.name

        root.title(f"Svacer ГОСТ triage — {job.name}")
        root.configure(bg=BG)
        root.minsize(980, 680)
        root.geometry("1120x760")
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.configure_style()
        self.build_ui()
        self.refresh()
        self.check_connection()

    def configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18), foreground=BLUE)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Card.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 11))
        style.configure("Value.TLabel", background=PANEL, foreground=BLUE, font=("Segoe UI Semibold", 17))
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(11, 7))
        style.configure("Accent.TButton", background=BLUE, foreground="#07131e")
        style.map("Accent.TButton", background=[("active", "#72c1ff"), ("disabled", "#40505e")])
        style.configure("Danger.TButton", background=RED, foreground="#21070a")
        style.map("Danger.TButton", background=[("active", "#ff8790"), ("disabled", "#5c4145")])
        style.configure("Horizontal.TProgressbar", troughcolor="#2a3744", background=BLUE, bordercolor=BG)
        style.configure("Treeview", background=PANEL, foreground=TEXT, fieldbackground=PANEL, rowheight=28)
        style.configure("Treeview.Heading", background="#273747", foreground=TEXT, font=("Segoe UI Semibold", 10))
        style.map("Treeview", background=[("selected", "#285b84")])

    def build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="SVACER ГОСТ TRIAGE", style="Title.TLabel").pack(side="left")
        self.connection_label = tk.Label(
            header, text="MCP: проверяется...", bg=BG, fg=YELLOW,
            font=("Segoe UI Semibold", 10), padx=8,
        )
        self.connection_label.pack(side="right")
        ttk.Label(outer, text=f"Компонент: {self.target_name}", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(outer, text=f"Задача: {self.job.name}", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(outer, text=str(self.job), style="Muted.TLabel").pack(anchor="w", pady=(0, 14))

        self.scope_var = tk.StringVar()
        ttk.Label(outer, textvariable=self.scope_var).pack(anchor="w")
        progress_line = ttk.Frame(outer)
        progress_line.pack(fill="x", pady=(6, 14))
        self.progress = ttk.Progressbar(progress_line, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_var = tk.StringVar(value="0/0")
        ttk.Label(progress_line, textvariable=self.progress_var, width=20).pack(side="left", padx=(12, 0))

        cards = ttk.Frame(outer)
        cards.pack(fill="x", pady=(0, 14))
        self.card_values: dict[str, tk.StringVar] = {}
        definitions = (
            ("confirmed", "Confirmed"), ("fp", "False Positive"),
            ("wont", "Won't fix"), ("unclear", "Unclear"), ("pending", "Pending"),
        )
        for column, (key, title) in enumerate(definitions):
            cards.columnconfigure(column, weight=1)
            card = ttk.Frame(cards, style="Panel.TFrame", padding=12)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
            ttk.Label(card, text=title, style="Card.TLabel").pack(anchor="w")
            value = tk.StringVar(value="0")
            self.card_values[key] = value
            ttk.Label(card, textvariable=value, style="Value.TLabel").pack(anchor="w", pady=(4, 0))

        details = ttk.Frame(outer, style="Panel.TFrame", padding=12)
        details.pack(fill="x", pady=(0, 14))
        self.verification_var = tk.StringVar()
        self.context_var = tk.StringVar()
        self.import_var = tk.StringVar()
        ttk.Label(details, textvariable=self.verification_var, style="Card.TLabel").pack(anchor="w")
        ttk.Label(details, textvariable=self.context_var, style="Card.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(details, textvariable=self.import_var, style="Card.TLabel").pack(anchor="w", pady=(4, 0))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("role", "saved", "batches", "state", "assigned", "updated")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
        headings = {
            "role": "Исполнитель", "saved": "Сохранено", "batches": "Партий",
            "state": "Состояние", "assigned": "Текущая партия", "updated": "Обновлено",
        }
        widths = {"role": 150, "saved": 95, "batches": 80, "state": 150, "assigned": 130, "updated": 105}
        for name in columns:
            self.table.heading(name, text=headings[name])
            self.table.column(name, width=widths[name], anchor="center")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.message_var = tk.StringVar(value="Анализ запущен. Панель обновляется автоматически.")
        self.message_label = tk.Label(
            outer, textvariable=self.message_var, bg=BG, fg=MUTED,
            font=("Segoe UI", 10), anchor="w", justify="left", wraplength=1050,
        )
        self.message_label.pack(fill="x", pady=(12, 8))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Пауза", command=lambda: self.pause(True)).pack(side="left", padx=(0, 5))
        ttk.Button(buttons, text="Продолжить", command=lambda: self.pause(False)).pack(side="left", padx=5)
        ttk.Button(buttons, text="Открыть папку", command=self.open_folder).pack(side="left", padx=5)
        ttk.Button(buttons, text="Обновить", command=self.refresh_and_check).pack(side="left", padx=5)
        ttk.Button(buttons, text="Подключить Svacer", command=self.connect).pack(side="left", padx=5)
        self.prepare_button = ttk.Button(
            buttons, text="Подготовить импорт", command=self.prepare_import, style="Accent.TButton"
        )
        self.prepare_button.pack(side="right", padx=(5, 0))
        self.send_button = ttk.Button(buttons, text="Отправить", command=self.send_import, style="Danger.TButton")
        self.send_button.pack(side="right", padx=5)

    def set_message(self, text: str, *, error: bool = False) -> None:
        self.message_var.set(text)
        self.message_label.configure(fg=RED if error else MUTED)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.prepare_button.configure(state=state)
        self.send_button.configure(state=state)

    def run_background(
        self,
        work: Callable[[], Any],
        done: Callable[[Any], None],
        busy_message: str,
    ) -> None:
        if self.busy:
            self.set_message("Дождитесь завершения текущей операции.", error=True)
            return
        self.set_busy(True)
        self.set_message(busy_message)

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:
                if not self.closed:
                    self.root.after(0, lambda: self.background_error(exc))
                return
            if not self.closed:
                self.root.after(0, lambda: self.background_done(done, result))

        threading.Thread(target=runner, daemon=True).start()

    def background_error(self, exc: Exception) -> None:
        self.set_busy(False)
        self.set_message(f"Ошибка: {friendly_mcp_error(exc)}", error=True)

    def background_done(self, done: Callable[[Any], None], result: Any) -> None:
        self.set_busy(False)
        done(result)

    def refresh(self) -> None:
        if self.closed:
            return
        if self.refresh_after_id is not None:
            self.root.after_cancel(self.refresh_after_id)
            self.refresh_after_id = None
        try:
            state = collect_state(self.job)
            total = int(state["total"])
            completed = int(state["completed"])
            percent = (100.0 * completed / total) if total else 0.0
            self.progress.configure(maximum=max(total, 1), value=completed)
            self.progress_var.set(f"{completed}/{total}  ({percent:.1f}%)")
            queue_text = "пауза" if state["paused"] else "работает"
            self.scope_var.set(
                f"Область: ГОСТ {state['inventory_total']}   |   уже размечено {state['already_reviewed']}   |   "
                f"для доразметки {total}   |   очередь: {queue_text}"
            )
            verdicts = state["by_verdict"]
            self.card_values["confirmed"].set(str(verdicts.get("Confirmed", 0)))
            self.card_values["fp"].set(str(verdicts.get("False Positive", 0)))
            self.card_values["wont"].set(str(verdicts.get("Won't fix", 0)))
            self.card_values["unclear"].set(str(verdicts.get("Unclear", 0)))
            self.card_values["pending"].set(str(state["pending"]))
            verification = state["verification"]
            required = sum(verification.values())
            self.verification_var.set(
                "Проверка Confirmed: "
                f"подтверждено {verification.get('verified', 0)} / {required}   |   "
                f"ожидает {verification.get('pending', 0)}   |   оспорено {verification.get('challenged', 0)}"
            )
            context = state["context"]
            self.context_var.set(
                f"Сохранённый контекст: ≈{format_count(int(context.get('estimated_tokens') or 0))} токенов   |   "
                f"основных ответов {context.get('primary_calls', 0)}   |   "
                f"проверок {context.get('verifier_calls', 0)}"
            )
            self.import_var.set(f"Импорт: {state['import']}")
            self.update_table(state)
            if state["errors"]:
                self.set_message("; ".join(state["errors"]), error=True)
        except Exception as exc:
            self.set_message(f"Ошибка обновления: {exc}", error=True)
        finally:
            if not self.closed:
                self.refresh_after_id = self.root.after(1000, self.refresh)

    def update_table(self, state: dict[str, Any]) -> None:
        rows: list[tuple[str, tuple[Any, ...]]] = []
        for number, worker in state["workers"].items():
            updated = "-" if not worker["updated"] else datetime.fromtimestamp(worker["updated"]).strftime("%H:%M:%S")
            rows.append((f"worker-{number}", (
                f"Агент {number}", worker["saved"], worker["batches"], worker["current_status"],
                f"{worker['current_saved']}/{worker['assigned']}", updated,
            )))
        for number, verifier in state["verifiers"].items():
            updated = "-" if not verifier["updated"] else datetime.fromtimestamp(verifier["updated"]).strftime("%H:%M:%S")
            rows.append((f"verifier-{number}", (
                f"Проверяющий {number}", verifier["saved"], verifier["batches"], verifier["current_status"],
                f"{verifier['current_saved']}/{verifier['assigned']}", updated,
            )))
        existing = set(self.table.get_children())
        wanted = {item_id for item_id, _ in rows}
        for item_id in existing - wanted:
            self.table.delete(item_id)
        for item_id, values in rows:
            if item_id in existing:
                self.table.item(item_id, values=values)
            else:
                self.table.insert("", "end", iid=item_id, values=values)

    def check_connection(self) -> None:
        def done(status: str) -> None:
            ok = status == "подключён"
            self.connection_label.configure(text=f"MCP: {status}", fg=GREEN if ok else YELLOW)
            self.set_message("Состояние Svacer обновлено.")

        self.run_background(
            lambda: check_mcp(self.mcp_url, self.token),
            done,
            "Проверяю подключение Svacer...",
        )

    def refresh_and_check(self) -> None:
        self.refresh()
        self.check_connection()

    def pause(self, paused: bool) -> None:
        set_pause(self.job, paused)
        if paused:
            self.set_message("Пауза запрошена: текущая партия завершится, но новая не будет выдана.")
        else:
            self.set_message("Продолжение разрешено. Если Codex остановлен, напишите ему «продолжи».")

    def open_folder(self) -> None:
        try:
            os.startfile(self.job)
            self.set_message("Папка задачи открыта.")
        except OSError as exc:
            self.set_message(f"Не удалось открыть папку: {exc}", error=True)

    def connect(self) -> None:
        try:
            start_svacer_reconnect(self.app_directory)
            self.connection_label.configure(text="MCP: ожидается вход", fg=YELLOW)
            self.set_message("Открыто окно входа. После запуска сервера нажмите «Обновить».")
        except Exception as exc:
            self.set_message(f"Не удалось открыть вход: {exc}", error=True)

    def prepare_import(self) -> None:
        state = collect_state(self.job)
        if not state["total"] or state["completed"] != state["total"]:
            self.set_message("Импорт можно готовить только после заполнения всех решений.", error=True)
            return

        def work() -> dict[str, Any]:
            status = check_mcp(self.mcp_url, self.token)
            if status != "подключён":
                raise RuntimeError(status)
            reply = asyncio.run(call_mcp_tool(
                self.mcp_url, self.token, "prepare_markup_import", {"job_directory": str(self.job)}
            ))
            return json.loads(reply)

        def done(payload: dict[str, Any]) -> None:
            self.set_message(
                f"Импорт подготовлен: {payload.get('marker_count')} маркеров, "
                f"конфликтов {payload.get('conflict_count')}. Проверьте preview перед отправкой."
            )

        self.run_background(work, done, "Проверяю маркеры и готовлю preview...")

    def send_import(self) -> None:
        preview_path = self.job / "svacer-import-preview.json"
        if not preview_path.exists():
            self.set_message("Сначала нажмите «Подготовить импорт».", error=True)
            return
        if (self.job / "svacer-import-attempt.json").exists():
            self.set_message("Попытка импорта уже записана; повтор заблокирован.", error=True)
            return
        preview = read_json(preview_path)
        force = bool(preview.get("requires_force"))
        expected = str(preview.get("force_confirmation" if force else "confirmation") or "")
        summary = (
            f"Маркеров: {preview.get('marker_count')}\n"
            f"Конфликтов: {preview.get('conflict_count')}\n"
            f"Режим: {'force' if force else 'none'}\n\n"
            "Следующий шаг изменит разметку Svacer. Продолжить?"
        )
        if not messagebox.askyesno("Отправка в Svacer", summary, parent=self.root):
            return
        typed = simpledialog.askstring(
            "Точное подтверждение",
            f"Введите дословно:\n\n{expected}",
            parent=self.root,
        )
        if typed != expected:
            self.set_message("Фраза не совпала. Ничего не отправлено.", error=True)
            return

        def work() -> dict[str, Any]:
            reply = asyncio.run(call_mcp_tool(
                self.mcp_url,
                self.token,
                "apply_markup_import",
                {
                    "job_directory": str(self.job),
                    "confirmation": typed,
                    "overwrite": "force" if force else "none",
                },
            ))
            return json.loads(reply)

        def done(payload: dict[str, Any]) -> None:
            verified = bool((payload.get("verification") or {}).get("verified"))
            self.set_message(
                "Отправка выполнена и подтверждена обратным экспортом."
                if verified else
                "Svacer принял запрос, но обратная проверка не прошла. Проверьте result/readback."
            )

        self.run_background(work, done, "Отправляю и выполняю обратную проверку...")

    def close(self) -> None:
        self.closed = True
        if self.refresh_after_id is not None:
            self.root.after_cancel(self.refresh_after_id)
            self.refresh_after_id = None
        self.root.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Графическая панель Svacer ГОСТ triage")
    parser.add_argument("--job")
    args = parser.parse_args()
    app_directory = Path(__file__).resolve().parent
    job = resolve_job(app_directory.parent, args.job)
    root = tk.Tk()
    TriageGui(root, job, app_directory)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
