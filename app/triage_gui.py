#!/usr/bin/env python3
"""Graphical dashboard and finding browser for local Svacer triage."""

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
    read_jsonl,
    resolve_job,
    set_pause,
    start_svacer_reconnect,
)


BG = "#0e151d"
SURFACE = "#17222d"
SURFACE_2 = "#1d2b38"
TEXT = "#e9f0f5"
MUTED = "#91a1ad"
BLUE = "#43a9ff"
GREEN = "#42cf7c"
YELLOW = "#f1be4b"
RED = "#ff6b75"
PURPLE = "#bd8cff"

VERDICT_HEADINGS = {"CONFIRMED", "FALSE POSITIVE", "WON'T FIX", "UNCLEAR"}
FILTERS = {
    "Все маркеры": "all",
    "Размеченные": "completed",
    "Ожидают анализа": "pending",
    "Confirmed": "Confirmed",
    "False Positive": "False Positive",
    "Won't fix": "Won't fix",
    "Unclear": "Unclear",
}


def format_count(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def short_file(value: Any) -> str:
    return Path(str(value or "").replace("\\", "/")).name or "—"


def comment_without_heading(value: Any) -> str:
    lines = str(value or "").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip().upper() in VERDICT_HEADINGS:
        lines.pop(0)
    return "\n".join(lines).strip()


def list_text(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "—"
    return "\n".join(f"• {item}" for item in value)


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
        self.marker_signature: tuple[int, ...] | None = None
        self.inventory_by_id: dict[str, dict[str, Any]] = {}
        self.trace_by_id: dict[str, dict[str, Any]] = {}
        self.decisions: list[dict[str, Any]] = []
        self.decision_by_id: dict[str, dict[str, Any]] = {}
        self.visible_marker_ids: list[str] = []
        self.current_marker_id: str | None = None

        job_data = read_json(job / "job.json") if (job / "job.json").exists() else {}
        repository = str(job_data.get("repository_url") or "").rstrip("/").rsplit("/", 1)[-1]
        if repository.endswith(".git"):
            repository = repository[:-4]
        git_ref = str(job_data.get("git_ref") or "")
        self.target_name = " ".join(part for part in (repository, git_ref) if part) or job.name

        root.title(f"Svacer Triage — {self.target_name}")
        root.configure(bg=BG)
        root.minsize(1060, 720)
        root.geometry("1280x840")
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.configure_style()
        self.build_ui()
        self.refresh()
        self.check_connection()

    def configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 20), foreground=TEXT)
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 12), foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT)
        style.configure("CardTitle.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI Semibold", 9), padding=(12, 7))
        style.configure("Accent.TButton", background=BLUE, foreground="#07131e")
        style.map("Accent.TButton", background=[("active", "#7bc5ff"), ("disabled", "#40505e")])
        style.configure("Danger.TButton", background=RED, foreground="#26070a")
        style.map("Danger.TButton", background=[("active", "#ff9299"), ("disabled", "#5c4145")])
        style.configure("Horizontal.TProgressbar", troughcolor="#263746", background=BLUE, bordercolor=BG)
        style.configure("Treeview", background=SURFACE, foreground=TEXT, fieldbackground=SURFACE, rowheight=29, borderwidth=0)
        style.configure("Treeview.Heading", background=SURFACE_2, foreground=TEXT, font=("Segoe UI Semibold", 9), relief="flat")
        style.map("Treeview", background=[("selected", "#265c84")], foreground=[("selected", "#ffffff")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(18, 9), font=("Segoe UI Semibold", 10))
        style.map("TNotebook.Tab", background=[("selected", SURFACE)], foreground=[("selected", TEXT)])
        style.configure("TCombobox", fieldbackground=SURFACE_2, background=SURFACE_2, foreground=TEXT, arrowcolor=TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE_2)], foreground=[("readonly", TEXT)])

    def build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(20, 16, 20, 14))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        title_box = ttk.Frame(header)
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="Svacer Triage", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_box, text=f"{self.target_name}  •  задача {self.job.name}", style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        self.connection_label = tk.Label(
            header, text="Svacer: проверка…", bg=SURFACE_2, fg=YELLOW,
            font=("Segoe UI Semibold", 9), padx=12, pady=7,
        )
        self.connection_label.pack(side="right")

        self.notebook = ttk.Notebook(outer)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self.overview_tab = ttk.Frame(self.notebook, padding=(0, 14, 0, 0))
        self.markers_tab = ttk.Frame(self.notebook, padding=(0, 14, 0, 0))
        self.notebook.add(self.overview_tab, text="Обзор")
        self.notebook.add(self.markers_tab, text="Маркеры")
        self.build_overview()
        self.build_markers()
        self.notebook.select(self.markers_tab)

        actions = ttk.Frame(outer)
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Пауза", command=lambda: self.pause(True)).pack(side="left", padx=(0, 5))
        ttk.Button(actions, text="Продолжить", command=lambda: self.pause(False)).pack(side="left", padx=5)
        ttk.Button(actions, text="Открыть результаты", command=self.open_folder).pack(side="left", padx=5)
        ttk.Button(actions, text="Войти в Svacer", command=self.connect).pack(side="left", padx=5)
        ttk.Button(actions, text="Обновить", command=self.refresh_and_check).pack(side="left", padx=5)
        self.send_button = ttk.Button(actions, text="Отправить", command=self.send_import, style="Danger.TButton")
        self.send_button.pack(side="right")
        self.prepare_button = ttk.Button(actions, text="Проверить перед отправкой", command=self.prepare_import, style="Accent.TButton")
        self.prepare_button.pack(side="right", padx=8)

        self.message_var = tk.StringVar(value="Панель обновляется автоматически.")
        self.message_label = tk.Label(
            outer, textvariable=self.message_var, bg=BG, fg=MUTED,
            font=("Segoe UI", 9), anchor="w", justify="left", wraplength=1200,
        )
        self.message_label.grid(row=3, column=0, sticky="ew", pady=(9, 0))

    def build_overview(self) -> None:
        progress_panel = ttk.Frame(self.overview_tab, style="Surface.TFrame", padding=15)
        progress_panel.pack(fill="x")
        top = ttk.Frame(progress_panel, style="Surface.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Прогресс анализа", style="Section.TLabel", background=SURFACE).pack(side="left")
        self.progress_var = tk.StringVar(value="0 из 0")
        ttk.Label(top, textvariable=self.progress_var, style="Surface.TLabel").pack(side="right")
        self.scope_var = tk.StringVar()
        ttk.Label(progress_panel, textvariable=self.scope_var, style="CardTitle.TLabel").pack(anchor="w", pady=(4, 8))
        self.progress = ttk.Progressbar(progress_panel, mode="determinate")
        self.progress.pack(fill="x")

        cards = ttk.Frame(self.overview_tab)
        cards.pack(fill="x", pady=10)
        self.card_values: dict[str, tk.StringVar] = {}
        definitions = (
            ("confirmed", "Confirmed", GREEN), ("fp", "False Positive", BLUE),
            ("wont", "Won't fix", YELLOW), ("unclear", "Unclear", PURPLE), ("pending", "Ожидают", MUTED),
        )
        for column, (key, title, color) in enumerate(definitions):
            cards.columnconfigure(column, weight=1)
            card = ttk.Frame(cards, style="Surface.TFrame", padding=(14, 11))
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 0))
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
            value = tk.StringVar(value="0")
            self.card_values[key] = value
            tk.Label(card, textvariable=value, bg=SURFACE, fg=color, font=("Segoe UI Semibold", 20)).pack(anchor="w", pady=(2, 0))

        details = ttk.Frame(self.overview_tab, style="Surface.TFrame", padding=(15, 11))
        details.pack(fill="x", pady=(0, 10))
        self.verification_var = tk.StringVar()
        self.context_var = tk.StringVar()
        self.import_var = tk.StringVar()
        ttk.Label(details, textvariable=self.verification_var, style="Surface.TLabel").pack(anchor="w")
        ttk.Label(details, textvariable=self.context_var, style="Surface.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(details, textvariable=self.import_var, style="Surface.TLabel").pack(anchor="w", pady=(4, 0))

        ttk.Label(self.overview_tab, text="Исполнители", style="Section.TLabel").pack(anchor="w", pady=(1, 6))
        table_frame = ttk.Frame(self.overview_tab)
        table_frame.pack(fill="both", expand=True)
        columns = ("role", "saved", "batches", "state", "assigned", "updated")
        self.worker_table = ttk.Treeview(table_frame, columns=columns, show="headings", height=6)
        headings = {"role": "Исполнитель", "saved": "Готово", "batches": "Партий", "state": "Состояние", "assigned": "Назначение", "updated": "Обновлено"}
        widths = {"role": 150, "saved": 85, "batches": 75, "state": 140, "assigned": 115, "updated": 100}
        for name in columns:
            self.worker_table.heading(name, text=headings[name])
            self.worker_table.column(name, width=widths[name], anchor="center")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.worker_table.yview)
        self.worker_table.configure(yscrollcommand=scroll.set)
        self.worker_table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def build_markers(self) -> None:
        toolbar = ttk.Frame(self.markers_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Поиск", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.search_var = tk.StringVar()
        search = tk.Entry(
            toolbar, textvariable=self.search_var, bg=SURFACE_2, fg=TEXT,
            insertbackground=TEXT, relief="flat", font=("Segoe UI", 10),
        )
        search.pack(side="left", fill="x", expand=True, ipady=7)
        search.bind("<KeyRelease>", lambda _event: self.apply_marker_filter())
        self.filter_var = tk.StringVar(value="Все маркеры")
        verdict_filter = ttk.Combobox(toolbar, textvariable=self.filter_var, values=list(FILTERS), state="readonly", width=21)
        verdict_filter.pack(side="left", padx=(8, 0), ipady=4)
        verdict_filter.bind("<<ComboboxSelected>>", lambda _event: self.apply_marker_filter())
        self.marker_count_var = tk.StringVar(value="0 маркеров")
        ttk.Label(toolbar, textvariable=self.marker_count_var, style="Muted.TLabel").pack(side="left", padx=(12, 0))

        paned = ttk.Panedwindow(self.markers_tab, orient="horizontal")
        paned.pack(fill="both", expand=True)
        list_panel = ttk.Frame(paned, style="Surface.TFrame", padding=1)
        detail_panel = ttk.Frame(paned, style="Surface.TFrame", padding=12)
        paned.add(list_panel, weight=2)
        paned.add(detail_panel, weight=3)

        columns = ("status", "detector", "file", "line")
        self.marker_table = ttk.Treeview(list_panel, columns=columns, show="headings", selectmode="browse")
        for name, title, width, anchor in (
            ("status", "Статус", 120, "w"), ("detector", "Детектор", 160, "w"),
            ("file", "Файл", 180, "w"), ("line", "Строка", 62, "center"),
        ):
            self.marker_table.heading(name, text=title)
            self.marker_table.column(name, width=width, anchor=anchor)
        self.marker_table.tag_configure("pending", foreground=MUTED)
        self.marker_table.tag_configure("confirmed", foreground=GREEN)
        self.marker_table.tag_configure("fp", foreground=BLUE)
        self.marker_table.tag_configure("wont", foreground=YELLOW)
        self.marker_table.tag_configure("unclear", foreground=PURPLE)
        self.marker_table.bind("<<TreeviewSelect>>", self.on_marker_selected)
        marker_scroll = ttk.Scrollbar(list_panel, orient="vertical", command=self.marker_table.yview)
        self.marker_table.configure(yscrollcommand=marker_scroll.set)
        self.marker_table.pack(side="left", fill="both", expand=True)
        marker_scroll.pack(side="right", fill="y")

        detail_head = ttk.Frame(detail_panel, style="Surface.TFrame")
        detail_head.pack(fill="x", pady=(0, 8))
        ttk.Label(detail_head, text="Карточка маркера", style="Section.TLabel", background=SURFACE).pack(side="left")
        ttk.Button(detail_head, text="Комментарий", command=self.copy_comment).pack(side="right")
        ttk.Button(detail_head, text="Копировать всё", command=self.copy_marker_info).pack(side="right", padx=(0, 6))
        ttk.Button(detail_head, text="Исходник", command=self.open_source).pack(side="right", padx=(0, 6))

        detail_body = ttk.Frame(detail_panel, style="Surface.TFrame")
        detail_body.pack(fill="both", expand=True)
        self.detail_text = tk.Text(
            detail_body, bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
            wrap="word", font=("Segoe UI", 10), padx=8, pady=4, spacing1=2, spacing3=5,
        )
        self.detail_text.tag_configure("title", font=("Segoe UI Semibold", 15), foreground=TEXT, spacing3=3)
        self.detail_text.tag_configure("meta", font=("Segoe UI", 9), foreground=MUTED, spacing3=10)
        self.detail_text.tag_configure("section", font=("Segoe UI Semibold", 10), foreground=BLUE, spacing1=10, spacing3=3)
        self.detail_text.tag_configure("body", foreground=TEXT)
        self.detail_text.tag_configure("pending", foreground=MUTED)
        detail_scroll = ttk.Scrollbar(detail_body, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set, state="disabled")
        self.detail_text.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        self.render_empty_detail()

    def set_message(self, text: str, *, error: bool = False) -> None:
        self.message_var.set(text)
        self.message_label.configure(fg=RED if error else MUTED)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.prepare_button.configure(state=state)
        self.send_button.configure(state=state)

    def run_background(self, work: Callable[[], Any], done: Callable[[Any], None], busy_message: str) -> None:
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
            self.progress_var.set(f"{completed} из {total}  •  {percent:.1f}%")
            queue_text = "приостановлена" if state["paused"] else "работает"
            self.scope_var.set(
                f"В снимке {state['inventory_total']}  •  ранее размечено {state['already_reviewed']}  •  "
                f"в этой задаче {total}  •  очередь {queue_text}"
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
                f"Независимая проверка Confirmed: {verification.get('verified', 0)} из {required}  •  "
                f"ожидает {verification.get('pending', 0)}  •  оспорено {verification.get('challenged', 0)}"
            )
            context = state["context"]
            self.context_var.set(
                f"Сохранённые материалы: ≈{format_count(int(context.get('estimated_tokens') or 0))} токенов  •  "
                f"ответов агентов {context.get('primary_calls', 0)}  •  проверок {context.get('verifier_calls', 0)}"
            )
            self.import_var.set(f"Отправка: {self.friendly_import_status(state['import'])}")
            self.update_worker_table(state)
            self.reload_markers_if_changed()
            if state["errors"]:
                self.set_message("; ".join(state["errors"]), error=True)
        except Exception as exc:
            self.set_message(f"Ошибка обновления: {exc}", error=True)
        finally:
            if not self.closed:
                self.refresh_after_id = self.root.after(1000, self.refresh)

    @staticmethod
    def friendly_import_status(value: Any) -> str:
        mapping = {"not prepared": "ещё не подготовлена", "prepared; waiting for confirmation": "проверено, ожидается подтверждение"}
        return mapping.get(str(value), str(value))

    def marker_files_signature(self) -> tuple[int, ...]:
        paths = [self.job / "markers.inventory.json", self.job / "decisions.jsonl"]
        raw = self.job / "raw"
        if raw.is_dir():
            paths.extend(sorted(raw.glob("*.json")))
        return tuple(path.stat().st_mtime_ns if path.exists() else 0 for path in paths)

    def reload_markers_if_changed(self) -> None:
        signature = self.marker_files_signature()
        if signature == self.marker_signature:
            return
        self.marker_signature = signature
        inventory = read_json(self.job / "markers.inventory.json")
        markers = inventory.get("markers") if isinstance(inventory, dict) else []
        self.inventory_by_id = {str(item.get("id")): item for item in markers if isinstance(item, dict) and item.get("id")}
        self.decisions = read_jsonl(self.job / "decisions.jsonl")
        self.decision_by_id = {str(item.get("marker_id")): item for item in self.decisions if item.get("marker_id")}
        self.trace_by_id = {}
        raw = self.job / "raw"
        if raw.is_dir():
            for path in sorted(raw.glob("*.json")):
                try:
                    payload = read_json(path)
                except (OSError, json.JSONDecodeError):
                    continue
                for marker in payload.get("markers") or []:
                    if isinstance(marker, dict) and marker.get("id"):
                        self.trace_by_id[str(marker["id"])] = marker
        self.apply_marker_filter()
        if self.current_marker_id in self.decision_by_id:
            self.render_marker(self.current_marker_id)

    def apply_marker_filter(self) -> None:
        selected = FILTERS.get(self.filter_var.get(), "all")
        query = self.search_var.get().strip().casefold()
        previous = self.current_marker_id
        children = self.marker_table.get_children()
        if children:
            self.marker_table.delete(*children)
        self.visible_marker_ids = []
        for decision in self.decisions:
            marker_id = str(decision.get("marker_id") or "")
            marker = self.inventory_by_id.get(marker_id, {})
            verdict = decision.get("verdict")
            if selected == "completed" and not verdict:
                continue
            if selected == "pending" and verdict:
                continue
            if selected not in {"all", "completed", "pending"} and verdict != selected:
                continue
            haystack = " ".join(str(value or "") for value in (
                marker_id, decision.get("warnClass"), decision.get("file"), marker.get("msg"),
                decision.get("comment"), decision.get("source"), decision.get("sink"),
            )).casefold()
            if query and query not in haystack:
                continue
            status = str(verdict or "Ожидает")
            tag = {"Confirmed": "confirmed", "False Positive": "fp", "Won't fix": "wont", "Unclear": "unclear"}.get(verdict, "pending")
            self.marker_table.insert("", "end", iid=marker_id, values=(status, decision.get("warnClass") or "—", short_file(decision.get("file")), decision.get("line") or "—"), tags=(tag,))
            self.visible_marker_ids.append(marker_id)
        self.marker_count_var.set(f"Показано: {len(self.visible_marker_ids)}")
        self.notebook.tab(self.markers_tab, text=f"Маркеры  {len(self.decisions)}")
        if previous in self.visible_marker_ids:
            self.marker_table.selection_set(previous)
            self.marker_table.see(previous)
        elif self.visible_marker_ids:
            first = self.visible_marker_ids[0]
            self.marker_table.selection_set(first)
            self.render_marker(first)
        else:
            self.render_empty_detail("По выбранному фильтру ничего не найдено.")

    def on_marker_selected(self, _event: Any = None) -> None:
        selection = self.marker_table.selection()
        if selection:
            self.render_marker(selection[0])

    def detail_insert(self, text: str, tag: str = "body") -> None:
        self.detail_text.insert("end", text, tag)

    def detail_section(self, title: str, value: Any) -> None:
        text = str(value or "").strip() or "—"
        self.detail_insert(f"\n{title}\n", "section")
        self.detail_insert(f"{text}\n", "body")

    def render_empty_detail(self, text: str = "Выберите маркер слева, чтобы посмотреть подробности.") -> None:
        self.current_marker_id = None
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_insert("Маркеры\n", "title")
        self.detail_insert(text, "pending")
        self.detail_text.configure(state="disabled")

    def render_marker(self, marker_id: str) -> None:
        self.current_marker_id = marker_id
        decision = self.decision_by_id.get(marker_id, {})
        marker = self.inventory_by_id.get(marker_id, {})
        traced = self.trace_by_id.get(marker_id, marker)
        verdict = decision.get("verdict") or "Ожидает анализа"
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_insert(f"{decision.get('warnClass') or marker.get('warnClass') or 'Маркер'}\n", "title")
        self.detail_insert(
            f"{short_file(decision.get('file') or marker.get('file'))}:{decision.get('line') or marker.get('line') or '—'}"
            f"   •   {verdict}   •   ID {marker_id}\n", "meta",
        )
        self.detail_section("Описание Svacer", marker.get("msg") or traced.get("msg"))
        if marker.get("function") or marker.get("mtid"):
            self.detail_section("Контекст", f"Функция: {marker.get('function') or '—'}\nMTID: {marker.get('mtid') or '—'}")
        traces = traced.get("traces") if isinstance(traced, dict) else None
        if isinstance(traces, list) and traces:
            lines: list[str] = []
            for trace in traces:
                lines.append(f"{trace.get('role') or 'роль'}:")
                for location in trace.get("locations") or []:
                    col = location.get("col")
                    suffix = f":{col}" if col else ""
                    lines.append(f"  • {short_file(location.get('file'))}:{location.get('line') or '—'}{suffix} — {location.get('info') or ''}")
            self.detail_section("Трасса", "\n".join(lines))
        else:
            self.detail_section("Трасса", "Полная трасса будет загружена перед анализом этого маркера.")
        if decision.get("verdict"):
            self.detail_section("Точка входа", decision.get("entrypoint"))
            self.detail_section("Source", decision.get("source"))
            self.detail_section("Проверки и ограничения", decision.get("control"))
            self.detail_section("Sink", decision.get("sink"))
            self.detail_section("Достижимость в сборке", decision.get("build_reachability"))
            self.detail_section("Достижимость в продукте", decision.get("product_reachability"))
            self.detail_section("Влияние", decision.get("impact"))
            self.detail_section("Доказательства", list_text(decision.get("evidence")))
            self.detail_section("Контраргументы", list_text(decision.get("counterevidence")))
            self.detail_section("Комментарий для Svacer", comment_without_heading(decision.get("comment")))
        else:
            self.detail_section("Статус", "Маркер ещё не анализировался.")
        self.detail_text.configure(state="disabled")
        self.detail_text.see("1.0")

    def copy_to_clipboard(self, text: str, message: str) -> None:
        if not text:
            self.set_message("Для выбранного маркера пока нечего копировать.", error=True)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_message(message)

    def copy_comment(self) -> None:
        decision = self.decision_by_id.get(self.current_marker_id or "", {})
        self.copy_to_clipboard(comment_without_heading(decision.get("comment")), "Комментарий скопирован без служебного заголовка.")

    def copy_marker_info(self) -> None:
        if not self.current_marker_id:
            self.set_message("Сначала выберите маркер.", error=True)
            return
        decision = self.decision_by_id.get(self.current_marker_id, {})
        marker = self.inventory_by_id.get(self.current_marker_id, {})
        text = "\n".join((
            f"{decision.get('warnClass')} — {decision.get('file')}:{decision.get('line')}",
            f"ID: {self.current_marker_id}",
            f"Описание: {marker.get('msg') or '—'}",
            f"Вердикт: {decision.get('verdict') or 'Ожидает анализа'}",
            f"Комментарий: {comment_without_heading(decision.get('comment')) or '—'}",
        ))
        self.copy_to_clipboard(text, "Карточка маркера скопирована.")

    def resolve_source_path(self, source: str) -> Path | None:
        raw = source.replace("\\", "/")
        candidates = [Path(source)]
        repository = self.job / "repository"
        candidates.append(repository / raw.lstrip("/"))
        for marker in ("/execroot/envoy/", "/envoy/"):
            if marker in raw:
                candidates.append(repository / raw.split(marker, 1)[1])
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def open_source(self) -> None:
        decision = self.decision_by_id.get(self.current_marker_id or "", {})
        source = str(decision.get("file") or "")
        path = self.resolve_source_path(source)
        if path is None:
            self.copy_to_clipboard(source, "Локальный файл сторонней зависимости не найден; исходный путь скопирован.")
            return
        try:
            os.startfile(path)
            self.set_message(f"Открыт {path.name}.")
        except OSError as exc:
            self.set_message(f"Не удалось открыть исходник: {exc}", error=True)

    def update_worker_table(self, state: dict[str, Any]) -> None:
        rows: list[tuple[str, tuple[Any, ...]]] = []
        for number, worker in state["workers"].items():
            updated = "—" if not worker["updated"] else datetime.fromtimestamp(worker["updated"]).strftime("%H:%M:%S")
            rows.append((f"worker-{number}", (f"Агент {number}", worker["saved"], worker["batches"], self.friendly_worker_status(worker["current_status"]), f"{worker['current_saved']}/{worker['assigned']}", updated)))
        for number, verifier in state["verifiers"].items():
            updated = "—" if not verifier["updated"] else datetime.fromtimestamp(verifier["updated"]).strftime("%H:%M:%S")
            rows.append((f"verifier-{number}", (f"Проверяющий {number}", verifier["saved"], verifier["batches"], self.friendly_worker_status(verifier["current_status"]), f"{verifier['current_saved']}/{verifier['assigned']}", updated)))
        existing = set(self.worker_table.get_children())
        wanted = {item_id for item_id, _ in rows}
        for item_id in existing - wanted:
            self.worker_table.delete(item_id)
        for item_id, values in rows:
            if item_id in existing:
                self.worker_table.item(item_id, values=values)
            else:
                self.worker_table.insert("", "end", iid=item_id, values=values)

    @staticmethod
    def friendly_worker_status(value: Any) -> str:
        return {"assigned": "назначено", "saved": "сохранено", "idle": "ожидает", "paused": "пауза"}.get(str(value), str(value))

    def check_connection(self) -> None:
        def done(status: str) -> None:
            ok = status == "подключён"
            self.connection_label.configure(text="Svacer подключён" if ok else "Svacer не подключён", fg=GREEN if ok else YELLOW)
            self.set_message("Подключение к Svacer работает." if ok else "Svacer сейчас недоступен. Нажмите «Войти в Svacer», затем «Обновить».", error=not ok)
        self.run_background(lambda: check_mcp(self.mcp_url, self.token), done, "Проверяю подключение к Svacer…")

    def refresh_and_check(self) -> None:
        self.refresh()
        self.check_connection()

    def pause(self, paused: bool) -> None:
        set_pause(self.job, paused)
        self.set_message("Очередь приостановлена после текущей партии." if paused else "Продолжение разрешено. Если задача Codex остановлена, напишите в ней «продолжи».")
        self.refresh()

    def open_folder(self) -> None:
        try:
            os.startfile(self.job)
            self.set_message("Папка с результатами открыта.")
        except OSError as exc:
            self.set_message(f"Не удалось открыть папку: {exc}", error=True)

    def connect(self) -> None:
        try:
            start_svacer_reconnect(self.app_directory)
            self.connection_label.configure(text="Ожидается вход в Svacer", fg=YELLOW)
            self.set_message("Выполните вход в открывшемся окне, затем нажмите «Обновить».")
        except Exception as exc:
            self.set_message(f"Не удалось открыть вход: {exc}", error=True)

    def prepare_import(self) -> None:
        state = collect_state(self.job)
        if not state["total"] or state["completed"] != state["total"]:
            self.set_message(f"Сначала завершите анализ: готово {state['completed']} из {state['total']}. Ничего не отправлено.", error=True)
            return
        def work() -> dict[str, Any]:
            status = check_mcp(self.mcp_url, self.token)
            if status != "подключён":
                raise RuntimeError(status)
            reply = asyncio.run(call_mcp_tool(self.mcp_url, self.token, "prepare_markup_import", {"job_directory": str(self.job)}))
            return json.loads(reply)
        def done(payload: dict[str, Any]) -> None:
            self.set_message(f"Проверка завершена: {payload.get('marker_count')} маркеров, конфликтов {payload.get('conflict_count')}. Теперь можно просмотреть preview.")
        self.run_background(work, done, "Проверяю решения и готовлю предварительный просмотр…")

    def send_import(self) -> None:
        preview_path = self.job / "svacer-import-preview.json"
        if not preview_path.exists():
            self.set_message("Сначала нажмите «Проверить перед отправкой».", error=True)
            return
        if (self.job / "svacer-import-attempt.json").exists():
            self.set_message("Попытка отправки уже записана; повтор заблокирован.", error=True)
            return
        preview = read_json(preview_path)
        force = bool(preview.get("requires_force"))
        expected = str(preview.get("force_confirmation" if force else "confirmation") or "")
        summary = f"Маркеров: {preview.get('marker_count')}\nКонфликтов: {preview.get('conflict_count')}\n\nСледующий шаг изменит разметку Svacer. Продолжить?"
        if not messagebox.askyesno("Отправка в Svacer", summary, parent=self.root):
            return
        typed = simpledialog.askstring("Точное подтверждение", f"Введите дословно:\n\n{expected}", parent=self.root)
        if typed != expected:
            self.set_message("Фраза не совпала. Ничего не отправлено.", error=True)
            return
        def work() -> dict[str, Any]:
            reply = asyncio.run(call_mcp_tool(self.mcp_url, self.token, "apply_markup_import", {"job_directory": str(self.job), "confirmation": typed, "overwrite": "force" if force else "none"}))
            return json.loads(reply)
        def done(payload: dict[str, Any]) -> None:
            verified = bool((payload.get("verification") or {}).get("verified"))
            self.set_message("Разметка отправлена и подтверждена обратной проверкой." if verified else "Svacer принял запрос, но обратная проверка не прошла. Откройте папку результатов.", error=not verified)
        self.run_background(work, done, "Отправляю разметку и выполняю обратную проверку…")

    def close(self) -> None:
        self.closed = True
        if self.refresh_after_id is not None:
            self.root.after_cancel(self.refresh_after_id)
            self.refresh_after_id = None
        self.root.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Графическая панель Svacer triage")
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
