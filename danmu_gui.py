import csv
import json
import ctypes
import os
import queue
import re
import danmu_batch_downloader as py_downloader
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib import parse as url_parse

APP_TITLE = "iDanmu"
DEFAULT_BASE_URL = "https://danmu2.dadaguai.edu.deal/zeabur"
DEFAULT_NAMING_RULE = "{基础名}"
BASE_TK_SCALING = 96 / 72
MAX_TK_SCALING = 1.8


def _enable_windows_dpi_awareness():
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class DanmuApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.is_fullscreen = False
        self.compact_layout = self.root.winfo_screenheight() <= 1080
        self._apply_safe_tk_scaling()
        self._fit_window(1280, 820, min_w=960, min_h=620)

        self.script_dir = Path(__file__).resolve().parent

        self.process = None
        self.stop_event = None
        self.log_queue = queue.Queue()

        self.results = []
        self.result_map = {}
        self.episode_map = {}
        self.current_anime = None
        self.queue_map = {}
        self.queue_seq = 1
        self.api_busy = False

        self.base_var = tk.StringVar(value=DEFAULT_BASE_URL)
        self.token_var = tk.StringVar(value="")
        self.keyword_var = tk.StringVar(value="子夜归")
        self.source_var = tk.StringVar(value="全部来源")
        self.output_var = tk.StringVar(value=str((self.script_dir / "downloads").resolve()))
        self.format_var = tk.StringVar(value="xml")
        self.naming_rule_var = tk.StringVar(value=DEFAULT_NAMING_RULE)
        self.concurrency_var = tk.StringVar(value="4")
        self.retry_var = tk.StringVar(value="4")
        self.throttle_var = tk.StringVar(value="300")
        self.timeout_var = tk.StringVar(value="60000")
        self.auto_scroll_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="状态: 待命")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text_var = tk.StringVar(value="进度: 0/0 (0%)")
        self.progress_total = 0
        self.progress_done = 0

        self._build_ui()
        self._ensure_window_visible()
        self._bind_events()
        self._parse_base_url(auto_log=False)
        self.root.after(120, self._tick_logs)

    def _apply_safe_tk_scaling(self):
        try:
            current = float(self.root.tk.call("tk", "scaling"))
        except Exception:
            return

        safe_scaling = max(BASE_TK_SCALING, min(MAX_TK_SCALING, current))
        if abs(safe_scaling - current) > 0.01:
            self.root.tk.call("tk", "scaling", safe_scaling)

    def _fit_window(self, pref_w: int, pref_h: int, min_w: int, min_h: int):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        max_w = max(1, sw - 24)
        max_h = max(1, sh - 72)
        fit_min_w = min(min_w, max_w)
        fit_min_h = min(min_h, max_h)
        w = max(fit_min_w, min(pref_w, max_w))
        h = max(fit_min_h, min(pref_h, max_h))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.maxsize(max_w, max_h)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(fit_min_w, fit_min_h)

    def _ensure_window_visible(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        max_w = max(1, sw - 24)
        max_h = max(1, sh - 72)

        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        cur_w = self.root.winfo_width()
        cur_h = self.root.winfo_height()

        target_w = min(max(req_w, cur_w), max_w)
        target_h = min(max(req_h, cur_h), max_h)
        x = max(0, (sw - target_w) // 2)
        y = max(0, (sh - target_h) // 2)

        self.root.maxsize(max_w, max_h)
        self.root.minsize(min(960, max_w), min(620, max_h))
        self.root.geometry(f"{target_w}x{target_h}+{x}+{y}")

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18), foreground="#0f766e")

        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=3)
        container.columnconfigure(1, weight=2)
        container.rowconfigure(2, weight=3)
        container.rowconfigure(3, weight=4)

        head = ttk.Frame(container)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(head, text="iDanmu", style="Title.TLabel").pack(anchor="w")
        ttk.Label(head, text="搜索剧名 -> 选来源 -> 加入全集 -> 一键下载", foreground="#64748b").pack(anchor="w")

        cfg = ttk.LabelFrame(container, text="基础配置", padding=10)
        cfg.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        cfg.columnconfigure(1, weight=1)
        cfg.columnconfigure(4, weight=1)

        ttk.Label(cfg, text="服务地址").grid(row=0, column=0, sticky="w")
        self.base_entry = ttk.Entry(cfg, textvariable=self.base_var)
        self.base_entry.grid(row=0, column=1, columnspan=4, sticky="ew", padx=(8, 0))

        ttk.Label(cfg, text="Token").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(cfg, textvariable=self.token_var, width=18).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        ttk.Button(cfg, text="解析地址", command=self._parse_base_url).grid(row=1, column=2, sticky="w", padx=(8, 0), pady=(6, 0))

        ttk.Label(cfg, text="输出目录").grid(row=1, column=3, sticky="w", padx=(18, 0), pady=(6, 0))
        ttk.Entry(cfg, textvariable=self.output_var).grid(row=1, column=4, sticky="ew", padx=(8, 0), pady=(6, 0))
        ttk.Button(cfg, text="选择", command=self._pick_output).grid(row=1, column=5, sticky="w", padx=(8, 0), pady=(6, 0))

        self._build_search(container, row=2, column=0, padx=(0, 8), pady=(0, 8))
        self._build_queue(container, row=2, column=1, pady=(0, 8))
        self._build_episodes(container, row=3, column=0, padx=(0, 8))
        self._build_run(container, row=3, column=1)

        ttk.Label(container, textvariable=self.status_var, foreground="#64748b").grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _build_search(self, parent, row=0, column=0, padx=(0, 0), pady=(0, 0)):
        card = ttk.LabelFrame(parent, text="搜索与来源", padding=10)
        card.grid(row=row, column=column, sticky="nsew", padx=padx, pady=pady)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        top = ttk.Frame(card)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Entry(top, textvariable=self.keyword_var).grid(row=0, column=0, sticky="ew")
        self.search_btn = ttk.Button(top, text="搜索", command=self.search)
        self.search_btn.grid(row=0, column=1, padx=(8, 0))

        tools = ttk.Frame(card)
        tools.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        ttk.Label(tools, text="来源:").pack(side="left")
        self.source_cb = ttk.Combobox(tools, textvariable=self.source_var, state="readonly", values=["全部来源"], width=14)
        self.source_cb.pack(side="left", padx=(6, 8))
        self.load_btn = ttk.Button(tools, text="加载剧集", command=self.load_selected_episodes)
        self.load_btn.pack(side="left")
        self.add_full_btn = ttk.Button(tools, text="加入该来源全集", command=self.add_full_from_selected)
        self.add_full_btn.pack(side="left", padx=(8, 0))

        tree_wrap = ttk.Frame(card)
        tree_wrap.grid(row=2, column=0, sticky="nsew")
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)

        result_height = 7 if self.compact_layout else 9
        self.result_tree = ttk.Treeview(tree_wrap, columns=("title", "source", "type", "aid"), show="headings", selectmode="browse", height=result_height)
        self.result_tree.heading("title", text="标题")
        self.result_tree.heading("source", text="来源")
        self.result_tree.heading("type", text="类型")
        self.result_tree.heading("aid", text="animeId")
        self.result_tree.column("title", width=420, anchor="w")
        self.result_tree.column("source", width=90, anchor="center")
        self.result_tree.column("type", width=90, anchor="center")
        self.result_tree.column("aid", width=90, anchor="center")
        self.result_tree.grid(row=0, column=0, sticky="nsew")

        ys = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=ys.set)
        ys.grid(row=0, column=1, sticky="ns")
    def _build_episodes(self, parent, row=0, column=0, padx=(0, 0), pady=(0, 0)):
        card = ttk.LabelFrame(parent, text="剧集", padding=10)
        card.grid(row=row, column=column, sticky="nsew", padx=padx, pady=pady)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(0, weight=1)

        wrap = ttk.Frame(card)
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        episode_height = 8 if self.compact_layout else 10
        self.ep_tree = ttk.Treeview(wrap, columns=("no", "title", "cid"), show="headings", selectmode="extended", height=episode_height)
        self.ep_tree.heading("no", text="集")
        self.ep_tree.heading("title", text="标题")
        self.ep_tree.heading("cid", text="commentId")
        self.ep_tree.column("no", width=70, anchor="center")
        self.ep_tree.column("title", width=430, anchor="w")
        self.ep_tree.column("cid", width=110, anchor="center")
        self.ep_tree.grid(row=0, column=0, sticky="nsew")

        ys = ttk.Scrollbar(wrap, orient="vertical", command=self.ep_tree.yview)
        self.ep_tree.configure(yscrollcommand=ys.set)
        ys.grid(row=0, column=1, sticky="ns")

        btns = ttk.Frame(card)
        btns.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(btns, text="全选", command=self.select_all_episodes).pack(side="left")
        ttk.Button(btns, text="加入所选集", command=self.add_selected_episodes).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="加入全集", command=self.add_all_episodes).pack(side="left", padx=(8, 0))

    def _build_queue(self, parent, row=0, column=0, padx=(0, 0), pady=(0, 0)):
        card = ttk.LabelFrame(parent, text="下载队列", padding=10)
        card.grid(row=row, column=column, sticky="nsew", padx=padx, pady=pady)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        ctl = ttk.Frame(card)
        ctl.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(ctl, text="删除所选", command=self.remove_selected_queue).pack(side="left")
        ttk.Button(ctl, text="清空", command=self.clear_queue).pack(side="left", padx=(8, 0))
        ttk.Button(ctl, text="导入", command=self.import_tasks).pack(side="left", padx=(8, 0))
        ttk.Button(ctl, text="导出", command=self.export_tasks).pack(side="left", padx=(8, 0))

        naming = ttk.Frame(card)
        naming.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        naming.columnconfigure(1, weight=1)
        ttk.Label(naming, text="命名规则").grid(row=0, column=0, sticky="w")
        self.naming_rule_entry = ttk.Entry(naming, textvariable=self.naming_rule_var)
        self.naming_rule_entry.grid(row=0, column=1, sticky="ew", padx=(6, 8))
        ttk.Button(naming, text="批量预命名", command=self.apply_queue_naming_rule).grid(row=0, column=2, sticky="w")
        ttk.Button(naming, text="规则说明", command=self.show_naming_rule_help).grid(row=0, column=3, sticky="w", padx=(6, 0))
        ttk.Label(
            naming,
            text="占位符: {基础名} {序号} {序号3} {弹幕ID} {番剧名} {剧集名} {任务类型}",
            foreground="#64748b",
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=(2, 0))

        token_row = ttk.Frame(naming)
        token_row.grid(row=2, column=1, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(token_row, text="常用:").pack(side="left")
        for label, token in [
            ("基础名", "{基础名}"),
            ("序号3", "{序号3}"),
            ("番剧名", "{番剧名}"),
            ("剧集名", "{剧集名}"),
            ("弹幕ID", "{弹幕ID}"),
            ("任务类型", "{任务类型}"),
            ("-", "-"),
            ("_", "_"),
        ]:
            ttk.Button(token_row, text=label, command=lambda t=token: self.insert_naming_token(t)).pack(side="left", padx=(4, 0))

        wrap = ttk.Frame(card)
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        queue_height = 7 if self.compact_layout else 9
        self.queue_tree = ttk.Treeview(wrap, columns=("name", "cid", "mode", "fmt"), show="headings", selectmode="extended", height=queue_height)
        self.queue_tree.heading("name", text="名称")
        self.queue_tree.heading("cid", text="commentId")
        self.queue_tree.heading("mode", text="模式")
        self.queue_tree.heading("fmt", text="格式")
        self.queue_tree.column("name", width=280, anchor="w")
        self.queue_tree.column("cid", width=100, anchor="center")
        self.queue_tree.column("mode", width=70, anchor="center")
        self.queue_tree.column("fmt", width=60, anchor="center")
        self.queue_tree.grid(row=0, column=0, sticky="nsew")

        ys = ttk.Scrollbar(wrap, orient="vertical", command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=ys.set)
        ys.grid(row=0, column=1, sticky="ns")

    def _build_run(self, parent, row=0, column=0, padx=(0, 0), pady=(0, 0)):
        card = ttk.LabelFrame(parent, text="执行", padding=10)
        card.grid(row=row, column=column, sticky="nsew", padx=padx, pady=pady)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(3, weight=1)

        opts = ttk.Frame(card)
        opts.grid(row=0, column=0, sticky="ew")
        ttk.Label(opts, text="格式").pack(side="left")
        ttk.Combobox(opts, textvariable=self.format_var, state="readonly", values=["xml", "json"], width=7).pack(side="left", padx=(6, 10))
        ttk.Label(opts, text="并发").pack(side="left")
        ttk.Entry(opts, textvariable=self.concurrency_var, width=6).pack(side="left", padx=(6, 10))
        ttk.Label(opts, text="重试").pack(side="left")
        ttk.Entry(opts, textvariable=self.retry_var, width=6).pack(side="left", padx=(6, 10))
        ttk.Label(opts, text="节流(ms)").pack(side="left")
        ttk.Entry(opts, textvariable=self.throttle_var, width=8).pack(side="left", padx=(6, 10))
        ttk.Label(opts, text="超时(ms)").pack(side="left")
        ttk.Entry(opts, textvariable=self.timeout_var, width=8).pack(side="left", padx=(6, 0))

        btns = ttk.Frame(card)
        btns.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        self.start_btn = ttk.Button(btns, text="开始下载", command=self.start_download)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="停止", command=self.stop_download, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="打开输出目录", command=self.open_output).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="清空日志", command=self.clear_log).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(btns, text="自动滚动", variable=self.auto_scroll_var).pack(side="left", padx=(12, 0))

        prog = ttk.Frame(card)
        prog.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        prog.columnconfigure(1, weight=1)
        ttk.Label(prog, textvariable=self.progress_text_var).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.progress_bar = ttk.Progressbar(prog, mode="determinate", maximum=100, variable=self.progress_var)
        self.progress_bar.grid(row=0, column=1, sticky="ew")

        log_wrap = ttk.Frame(card)
        log_wrap.grid(row=3, column=0, sticky="nsew")
        log_wrap.columnconfigure(0, weight=1)
        log_wrap.rowconfigure(0, weight=1)
        log_height = 10 if self.compact_layout else 14
        self.log_text = tk.Text(
            log_wrap,
            bg="#1f2933",
            fg="#dce4ea",
            relief="flat",
            font=("Consolas", 10),
            padx=10,
            pady=10,
            height=log_height,
            wrap="none",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_y = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log_text.yview)
        log_x = ttk.Scrollbar(log_wrap, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=log_y.set, xscrollcommand=log_x.set)
        log_y.grid(row=0, column=1, sticky="ns")
        log_x.grid(row=1, column=0, sticky="ew")
        self.log_text.tag_configure("ok", foreground="#9ef0b3")
        self.log_text.tag_configure("err", foreground="#ff8a8a")
        self.log_text.tag_configure("title", foreground="#9cc7ff")
        self.log_text.tag_configure("meta", foreground="#aab6c3")
        self.log_text.insert("end", "准备就绪。\n")
        self.log_text.configure(state="disabled")

    def _bind_events(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.base_entry.bind("<FocusOut>", lambda _e: self._parse_base_url())
        self.base_entry.bind("<Return>", lambda _e: self._parse_base_url())
        self.source_cb.bind("<<ComboboxSelected>>", lambda _e: self.render_results())
        self.result_tree.bind("<Double-1>", lambda _e: self.load_selected_episodes())
        self.root.bind("<F11>", self._on_toggle_fullscreen)
        self.root.bind("<Escape>", self._on_exit_fullscreen)

    def _set_fullscreen(self, enabled: bool):
        enabled = bool(enabled)
        self.is_fullscreen = enabled

        if enabled:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            # Remove normal-window maxsize caps before entering fullscreen.
            self.root.maxsize(max(sw, 100000), max(sh, 100000))
            self.root.geometry(f"{sw}x{sh}+0+0")

        try:
            self.root.attributes("-fullscreen", enabled)
        except tk.TclError:
            if enabled:
                try:
                    self.root.state("zoomed")
                except tk.TclError:
                    sw = self.root.winfo_screenwidth()
                    sh = self.root.winfo_screenheight()
                    self.root.geometry(f"{sw}x{sh}+0+0")
            else:
                try:
                    self.root.state("normal")
                except tk.TclError:
                    pass
                self._ensure_window_visible()

    def _on_toggle_fullscreen(self, _event=None):
        self._set_fullscreen(not self.is_fullscreen)
        return "break"

    def _on_exit_fullscreen(self, _event=None):
        if self.is_fullscreen:
            self._set_fullscreen(False)
            return "break"
        return None

    def _refresh_progress(self):
        total = max(0, int(self.progress_total))
        done = max(0, min(int(self.progress_done), total)) if total else 0
        percent = (done / total * 100.0) if total else 0.0
        self.progress_var.set(percent)
        self.progress_text_var.set(f"进度: {done}/{total} ({percent:.0f}%)")

    def _reset_progress(self, total=0):
        self.progress_total = max(0, int(total))
        self.progress_done = 0
        self._refresh_progress()

    def _update_progress_from_log(self, msg: str):
        total_match = re.search(r"Total tasks:\s*(\d+)", msg)
        if total_match:
            self.progress_total = int(total_match.group(1))
            self.progress_done = 0
            self._refresh_progress()

        done_inc = msg.count("OK ->") + msg.count("FAILED ->")
        if done_inc > 0:
            self.progress_done += done_inc
            self._refresh_progress()

        if "No tasks to run." in msg:
            self.progress_total = 0
            self.progress_done = 0
            self._refresh_progress()

    def _pick_log_tag(self, text: str):
        if "FAILED ->" in text or "启动失败" in text or "参数错误" in text:
            return "err"
        if "OK ->" in text:
            return "ok"
        if "===" in text:
            return "title"
        if text.startswith("API:") or text.startswith("Output:") or text.startswith("Total tasks:") or text.startswith("Concurrency:"):
            return "meta"
        return None

    def _append_log(self, text: str):
        self.log_text.configure(state="normal")
        tag = self._pick_log_tag(text)
        if tag:
            self.log_text.insert("end", text, tag)
        else:
            self.log_text.insert("end", text)
        if self.auto_scroll_var.get():
            self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_api_busy(self, busy: bool):
        self.api_busy = busy
        state = "disabled" if busy else "normal"
        for widget in [self.search_btn, self.load_btn, self.add_full_btn]:
            widget.configure(state=state)
        self.root.config(cursor="watch" if busy else "")
        self.root.update_idletasks()

    def _run_api_task(self, start_status: str, fail_title: str, worker, on_success):
        if self.api_busy:
            return
        self.status_var.set(start_status)
        self._set_api_busy(True)

        def run():
            try:
                result = worker()
            except Exception as exc:
                self.root.after(0, lambda exc=exc: self._finish_api_error(fail_title, exc))
                return
            self.root.after(0, lambda result=result: self._finish_api_success(on_success, result))

        threading.Thread(target=run, daemon=True).start()

    def _finish_api_success(self, on_success, result):
        try:
            on_success(result)
        finally:
            self._set_api_busy(False)

    def _finish_api_error(self, title: str, exc: Exception):
        self._set_api_busy(False)
        self.status_var.set("状态: 待命")
        messagebox.showerror(title, str(exc))

    def _set_running(self, running: bool):
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        self.status_var.set("状态: 下载中..." if running else "状态: 待命")

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._reset_progress(0)

    def _pick_output(self):
        p = filedialog.askdirectory(initialdir=self.output_var.get().strip() or str(self.script_dir))
        if p:
            self.output_var.set(p)

    def _parse_base_url(self, auto_log=True):
        base = self.base_var.get().strip()
        token = self.token_var.get().strip()
        if not base:
            return None

        candidate = base if re.match(r"^https?://", base, flags=re.I) else "https://" + base
        parsed = url_parse.urlsplit(candidate)
        if not parsed.netloc:
            return None

        segs = [s for s in parsed.path.split("/") if s]
        auto_token = None
        if segs:
            tail = segs[-1]
            if not token:
                token = tail
                segs = segs[:-1]
                auto_token = tail
            elif token == tail:
                segs = segs[:-1]

        base_path = "/" + "/".join(segs) if segs else ""
        norm_base = f"{parsed.scheme}://{parsed.netloc}{base_path}"
        if self.base_var.get().strip() != norm_base:
            self.base_var.set(norm_base)
        if self.token_var.get().strip() != token:
            self.token_var.set(token)
        if auto_log and auto_token:
            self._append_log(f"已自动识别 token: {auto_token}\n")

        return norm_base, token
    def api_root(self):
        parsed = self._parse_base_url(auto_log=False)
        if not parsed:
            raise RuntimeError("请先填写正确的服务地址")
        base, token = parsed
        root = base.rstrip("/")
        if token:
            root += "/" + url_parse.quote(token)
        return root

    def request_json(self, method, path, query=None, payload=None, timeout=35):
        root = self.api_root()
        try:
            retry_count = max(0, int(self.retry_var.get().strip()))
        except Exception:
            retry_count = 4

        try:
            return py_downloader.request_json_with_retry(
                api_root=root,
                path_name=path,
                method=method,
                query=query,
                body=payload,
                timeout_ms=max(1000, int(timeout * 1000)),
                retries=max(2, retry_count),
                retry_delay_ms=2000,
                user_agent="iDanmu/1.0",
            )
        except py_downloader.HttpError as exc:
            detail = (exc.body or "").strip()
            raise RuntimeError(f"HTTP {exc.status}: {detail[:300]}") from exc
        except Exception as exc:
            raise RuntimeError(f"请求失败: {exc}") from exc

    def source_of(self, anime):
        source = (anime.get("source") or "").strip()
        if source:
            return source
        title = anime.get("animeTitle", "")
        m = re.search(r"\bfrom\s+([a-zA-Z0-9_]+)\s*$", title, flags=re.I)
        return m.group(1).lower() if m else "unknown"

    def short(self, text, n=64):
        text = (text or "").strip()
        return text if len(text) <= n else text[: n - 1] + "…"

    def _sanitize_output_stem(self, raw_name: str) -> str:
        stem = Path((raw_name or "").strip()).name
        lowered = stem.lower()
        if lowered.endswith(".xml") or lowered.endswith(".json"):
            stem = stem.rsplit(".", 1)[0]
        sanitizer = getattr(py_downloader, "_sanitize_windows_filename", None)
        if callable(sanitizer):
            return sanitizer(stem)
        return re.sub(r'[<>:"/\\|?*]', "_", stem).strip() or "danmu"

    def _queue_base_name(self, task: dict, fallback_index: int) -> str:
        for key in ("_base_name", "name", "fileName", "filename", "animeTitle", "anime"):
            value = task.get(key)
            text = str(value).strip() if value is not None else ""
            if text:
                return text
        return f"task-{fallback_index}"

    def insert_naming_token(self, token: str):
        entry = getattr(self, "naming_rule_entry", None)
        if entry is None:
            return
        try:
            sel_first = entry.index("sel.first")
            sel_last = entry.index("sel.last")
            entry.delete(sel_first, sel_last)
            insert_at = sel_first
        except tk.TclError:
            insert_at = entry.index("insert")
        entry.insert(insert_at, token)
        entry.icursor(f"{insert_at}+{len(token)}c")
        entry.focus_set()

    def show_naming_rule_help(self):
        messagebox.showinfo(
            "命名规则说明",
            "命名规则会在加入队列后和开始下载前批量应用。\n\n"
            "推荐中文占位符：\n"
            "  {基础名}  初始任务名\n"
            "  {序号}    队列序号（1,2,3...）\n"
            "  {序号3}   三位序号（001,002...）\n"
            "  {弹幕ID}  commentId\n"
            "  {番剧名}  番剧标题\n"
            "  {剧集名}  剧集标题\n"
            "  {任务类型} commentId 等\n\n"
            "示例：\n"
            "  {序号3}-{番剧名}-{剧集名}\n"
            "  {基础名}-{弹幕ID}",
        )

    def _normalize_naming_rule(self, naming_rule: str) -> str:
        rule = naming_rule or DEFAULT_NAMING_RULE
        alias_map = {
            "{基础名}": "{base}",
            "{原名}": "{base}",
            "{当前名}": "{name}",
            "{序号}": "{index}",
            "{序号3}": "{index:03d}",
            "{弹幕ID}": "{commentId}",
            "{番剧名}": "{animeTitle}",
            "{剧集名}": "{episodeTitle}",
            "{任务类型}": "{mode}",
        }
        for cn_alias, en_token in alias_map.items():
            rule = rule.replace(cn_alias, en_token)
        return rule

    def _render_queue_name(self, task: dict, index: int, naming_rule: str) -> str:
        base_name = self._queue_base_name(task, index)
        rule = self._normalize_naming_rule(naming_rule.strip() or DEFAULT_NAMING_RULE)
        values = {
            "index": index,
            "base": base_name,
            "name": task.get("name") or base_name,
            "mode": task.get("mode") or "custom",
            "commentId": task.get("commentId") or "",
            "animeTitle": task.get("animeTitle") or "",
            "episodeTitle": task.get("episodeTitle") or "",
            "episodeNo": task.get("episodeNo") or "",
        }
        try:
            rendered = rule.format_map(values)
        except KeyError as exc:
            raise RuntimeError(f"命名规则占位符无效: {exc.args[0]}") from exc
        except ValueError as exc:
            raise RuntimeError(f"命名规则格式错误: {exc}") from exc
        return self._sanitize_output_stem(str(rendered).strip() or base_name)

    def apply_queue_naming_rule(self, show_error=True, log_action=True):
        rule = self.naming_rule_var.get().strip() or DEFAULT_NAMING_RULE
        updates = []
        try:
            for index, iid in enumerate(self.queue_tree.get_children(), start=1):
                task = self.queue_map.get(iid)
                if not task:
                    continue
                task_copy = dict(task)
                task_copy["_base_name"] = self._queue_base_name(task_copy, index)
                task_copy["name"] = self._render_queue_name(task_copy, index, rule)
                task_copy["format"] = str(task_copy.get("format") or self.format_var.get().strip() or "xml").lower()
                updates.append((iid, task_copy))
        except Exception as exc:
            if show_error:
                messagebox.showerror("命名规则错误", str(exc))
            return False

        for iid, task_copy in updates:
            self.queue_map[iid] = task_copy
            self.queue_tree.item(
                iid,
                values=(
                    self.short(task_copy.get("name", ""), 60),
                    task_copy.get("commentId", "-"),
                    task_copy.get("mode", "custom"),
                    task_copy.get("format", "xml"),
                ),
            )

        if log_action and updates:
            self._append_log(f"已按命名规则预命名: {rule}\n")
        return True

    def search(self):
        keyword = self.keyword_var.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入关键词")
            return
        self._run_api_task(
            start_status="状态: 搜索中...",
            fail_title="搜索失败",
            worker=lambda: self.request_json("GET", "/api/v2/search/anime", query={"keyword": keyword}),
            on_success=lambda data, keyword=keyword: self._on_search_done(keyword, data),
        )

    def _on_search_done(self, keyword, data):
        self.results = []
        for anime in data.get("animes") or []:
            self.results.append(
                {
                    "animeId": anime.get("animeId"),
                    "title": anime.get("animeTitle", ""),
                    "source": self.source_of(anime),
                    "type": anime.get("typeDescription") or anime.get("type") or "",
                    "raw": anime,
                }
            )

        sources = sorted({x["source"] for x in self.results})
        self.source_cb.configure(values=["全部来源"] + sources)
        self.source_var.set("全部来源")
        self.render_results()
        self.status_var.set(f"状态: 搜索完成，共 {len(self.results)} 条")
        self._append_log(f"搜索完成: {keyword} -> {len(self.results)} 条\n")

    def render_results(self):
        for iid in self.result_tree.get_children():
            self.result_tree.delete(iid)
        self.result_map.clear()

        source = self.source_var.get().strip()
        rows = self.results if source in ["", "全部来源"] else [x for x in self.results if x["source"] == source]

        for i, item in enumerate(rows, start=1):
            iid = f"r-{i}-{item['animeId']}"
            self.result_map[iid] = item
            self.result_tree.insert(
                "",
                "end",
                iid=iid,
                values=(self.short(item["title"], 74), item["source"], self.short(item["type"], 18), item["animeId"]),
            )

    def selected_result(self):
        sel = self.result_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个来源")
            return None
        return self.result_map.get(sel[0])

    def fetch_episodes(self, anime_id):
        data = self.request_json("GET", f"/api/v2/bangumi/{anime_id}")
        return (data.get("bangumi") or {}).get("episodes") or []

    def render_episodes(self, anime, episodes):
        for iid in self.ep_tree.get_children():
            self.ep_tree.delete(iid)
        self.episode_map.clear()
        self.current_anime = anime

        for i, ep in enumerate(episodes, start=1):
            cid = ep.get("episodeId")
            if cid is None:
                continue
            iid = f"ep-{i}-{cid}"
            self.episode_map[iid] = ep
            no = str(ep.get("episodeNumber") or i)
            title = ep.get("episodeTitle") or f"第{no}集"
            self.ep_tree.insert("", "end", iid=iid, values=(no, self.short(title, 72), cid))

        self._append_log(f"已加载剧集: {self.short(anime['title'], 36)} [{anime['source']}] -> {len(self.episode_map)} 集\n")

    def load_selected_episodes(self):
        anime = self.selected_result()
        if not anime:
            return
        self._run_api_task(
            start_status="状态: 加载剧集中...",
            fail_title="加载失败",
            worker=lambda: self.fetch_episodes(anime["animeId"]),
            on_success=lambda episodes, anime=anime: self._on_load_episodes_done(anime, episodes),
        )

    def _on_load_episodes_done(self, anime, episodes):
        self.render_episodes(anime, episodes)
        self.status_var.set(f"状态: 当前来源 {anime['source']}，共 {len(episodes)} 集")

    def _tasks_from_episodes(self, episodes, anime):
        fmt = self.format_var.get().strip() or "xml"
        tasks = []
        clean_title = re.sub(r"\s*from\s+\w+\s*$", "", anime.get("title", ""), flags=re.I).strip() or "unknown"
        for i, ep in enumerate(episodes, start=1):
            cid = ep.get("episodeId")
            if cid is None:
                continue
            no = str(ep.get("episodeNumber") or i)
            title = ep.get("episodeTitle") or f"第{no}集"
            base_name = f"{clean_title}-第{no}集-{title}"
            tasks.append(
                {
                    "_base_name": base_name,
                    "name": base_name,
                    "animeTitle": clean_title,
                    "episodeTitle": title,
                    "episodeNo": no,
                    "commentId": int(cid) if str(cid).isdigit() else cid,
                    "format": fmt,
                    "mode": "commentId",
                }
            )
        return tasks

    def add_tasks(self, tasks):
        existing = {str(t.get("commentId")) for t in self.queue_map.values() if t.get("commentId") is not None}
        added = 0
        skip = 0
        for task in tasks:
            task_copy = dict(task)
            cid = task.get("commentId")
            if cid is not None and str(cid) in existing:
                skip += 1
                continue
            iid = f"q-{self.queue_seq}"
            self.queue_seq += 1
            task_copy["mode"] = task_copy.get("mode") or "custom"
            task_copy["format"] = str(task_copy.get("format") or self.format_var.get().strip() or "xml").lower()
            task_copy["_base_name"] = self._queue_base_name(task_copy, self.queue_seq - 1)
            task_copy["name"] = str(task_copy.get("name") or task_copy["_base_name"])
            self.queue_map[iid] = task_copy
            self.queue_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    self.short(task_copy.get("name", ""), 60),
                    task_copy.get("commentId", "-"),
                    task_copy.get("mode", "custom"),
                    task_copy.get("format", "xml"),
                ),
            )
            if cid is not None:
                existing.add(str(cid))
            added += 1
        if added > 0:
            self.apply_queue_naming_rule(show_error=False, log_action=False)
        self._append_log(f"加入队列: +{added}，重复跳过: {skip}\n")

    def add_full_from_selected(self):
        anime = self.selected_result()
        if not anime:
            return
        self._run_api_task(
            start_status="状态: 正在加载全集...",
            fail_title="失败",
            worker=lambda: self.fetch_episodes(anime["animeId"]),
            on_success=lambda episodes, anime=anime: self._on_add_full_done(anime, episodes),
        )

    def _on_add_full_done(self, anime, episodes):
        self.render_episodes(anime, episodes)
        self.add_tasks(self._tasks_from_episodes(episodes, anime))
        self.status_var.set(f"状态: 已加入来源 {anime['source']} 全集")

    def select_all_episodes(self):
        items = self.ep_tree.get_children()
        if items:
            self.ep_tree.selection_set(items)

    def add_selected_episodes(self):
        if not self.current_anime:
            messagebox.showwarning("提示", "请先加载剧集")
            return
        sel = self.ep_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择剧集")
            return
        episodes = [self.episode_map[i] for i in sel if i in self.episode_map]
        self.add_tasks(self._tasks_from_episodes(episodes, self.current_anime))

    def add_all_episodes(self):
        if not self.current_anime or not self.episode_map:
            messagebox.showwarning("提示", "请先加载剧集")
            return
        self.add_tasks(self._tasks_from_episodes(list(self.episode_map.values()), self.current_anime))

    def remove_selected_queue(self):
        for iid in self.queue_tree.selection():
            self.queue_tree.delete(iid)
            self.queue_map.pop(iid, None)
        if self.queue_tree.get_children():
            self.apply_queue_naming_rule(show_error=False, log_action=False)

    def clear_queue(self):
        for iid in self.queue_tree.get_children():
            self.queue_tree.delete(iid)
        self.queue_map.clear()

    def collect_tasks(self):
        tasks = []
        for iid in self.queue_tree.get_children():
            task = self.queue_map.get(iid)
            if not task:
                continue
            pure = {k: v for k, v in task.items() if k != "mode" and not str(k).startswith("_")}
            if not pure.get("format"):
                pure["format"] = self.format_var.get().strip() or "xml"
            tasks.append(pure)
        return tasks

    def import_tasks(self):
        p = filedialog.askopenfilename(title="导入任务", filetypes=[("JSONL", "*.jsonl"), ("JSON", "*.json"), ("CSV", "*.csv"), ("All", "*.*")])
        if not p:
            return
        try:
            tasks = self.read_tasks(Path(p))
            self.add_tasks(tasks)
            self._append_log(f"导入任务: {p} ({len(tasks)} 条)\n")
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))

    def export_tasks(self):
        tasks = self.collect_tasks()
        if not tasks:
            messagebox.showwarning("提示", "队列为空")
            return
        p = filedialog.asksaveasfilename(title="导出任务", defaultextension=".jsonl", filetypes=[("JSONL", "*.jsonl"), ("JSON", "*.json")])
        if not p:
            return
        out = Path(p)
        try:
            if out.suffix.lower() == ".json":
                out.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                out.write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in tasks) + "\n", encoding="utf-8")
            self._append_log(f"已导出任务: {p}\n")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    def read_tasks(self, path: Path):
        text = path.read_text(encoding="utf-8").replace("\ufeff", "")
        ext = path.suffix.lower()
        tasks = []
        if ext in [".jsonl", ".ndjson", ".txt"]:
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                item = json.loads(line)
                item["mode"] = item.get("mode", "custom")
                tasks.append(item)
        elif ext == ".json":
            data = json.loads(text)
            arr = data if isinstance(data, list) else data.get("tasks", [])
            for item in arr:
                item["mode"] = item.get("mode", "custom")
                tasks.append(item)
        elif ext == ".csv":
            reader = csv.DictReader(text.splitlines())
            for row in reader:
                row["mode"] = row.get("mode") or "custom"
                tasks.append(row)
        else:
            raise RuntimeError("仅支持 json/jsonl/csv")
        return tasks
    def start_download(self):
        if self.process is not None:
            return

        if not self.queue_tree.get_children():
            messagebox.showwarning("提示", "下载队列为空")
            return
        if not self.apply_queue_naming_rule(show_error=True, log_action=False):
            return
        tasks = self.collect_tasks()
        if not tasks:
            messagebox.showwarning("提示", "下载队列为空")
            return
        self._reset_progress(len(tasks))

        try:
            parsed = self._parse_base_url(auto_log=False)
            if not parsed:
                raise RuntimeError("服务地址无效")
            base, token = parsed
            concurrency = max(1, int(self.concurrency_var.get().strip()))
            retries = max(0, int(self.retry_var.get().strip()))
            throttle = max(0, int(self.throttle_var.get().strip()))
            timeout = max(1000, int(self.timeout_var.get().strip()))
            fmt = self.format_var.get().strip() or "xml"
            naming_rule = self.naming_rule_var.get().strip() or DEFAULT_NAMING_RULE
            output = self.output_var.get().strip() or str((self.script_dir / "downloads").resolve())
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self._append_log("\n=== 开始下载 ===\n")
        self._append_log(
            f"参数: base={base}, token={'***' if token else '(none)'}, format={fmt}, naming_rule={naming_rule}, "
            f"concurrency={concurrency}, retries={retries}, throttle_ms={throttle}, timeout_ms={timeout}\n\n"
        )
        self._set_running(True)
        self.stop_event = threading.Event()

        def run():
            try:
                exit_code = py_downloader.run_download(
                    {
                        "base_url": base,
                        "token": token,
                        "output": output,
                        "format": fmt,
                        "naming_rule": "{base}",
                        "concurrency": concurrency,
                        "retries": retries,
                        "throttle_ms": throttle,
                        "timeout_ms": timeout,
                    },
                    tasks_override=tasks,
                    log_fn=lambda text: self.log_queue.put(text),
                    is_cancelled=self.stop_event.is_set,
                )
                self.log_queue.put(f"\n=== 下载结束，退出码: {exit_code} ===\n")
            except Exception as exc:
                self.log_queue.put(f"\n启动失败: {exc}\n")
            finally:
                self.process = None
                self.stop_event = None
                self.log_queue.put("__DONE__")

        self.process = threading.Thread(target=run, daemon=True)
        self.process.start()

    def stop_download(self):
        if self.process is None:
            return
        if self.stop_event is not None and not self.stop_event.is_set():
            self.stop_event.set()
            self._append_log("\n已请求停止任务（等待当前请求完成）...\n")

    def open_output(self):
        folder = self.output_var.get().strip() or str((self.script_dir / "downloads").resolve())
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def _tick_logs(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__DONE__":
                    self._set_running(False)
                else:
                    self._update_progress_from_log(msg)
                    self._append_log(msg)
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._tick_logs)

    def on_close(self):
        if self.process is not None:
            if not messagebox.askyesno("确认退出", "当前任务正在运行，确定退出吗？"):
                return
            if self.stop_event is not None:
                self.stop_event.set()
        self.root.destroy()


def main():
    _enable_windows_dpi_awareness()
    root = tk.Tk()
    DanmuApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
