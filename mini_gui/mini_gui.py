import ctypes
import os
import queue
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from urllib import parse as url_parse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import danmu_batch_downloader as py_downloader  # noqa: E402
import local_danmu_api  # noqa: E402
import window_workarea  # noqa: E402

APP_TITLE = "iDanmu_Speed Mini"
DEFAULT_SERVICE_URL = local_danmu_api.DEFAULT_LOCAL_BASE_URL
DEFAULT_TOKEN = local_danmu_api.DEFAULT_LOCAL_TOKEN
DEFAULT_NAMING_RULE = "{base}"
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


class MiniDanmuGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.is_fullscreen = False
        self._apply_safe_tk_scaling()
        self._fit_window(1100, 760, min_w=900, min_h=620)
        self.root.configure(bg="#f6f2ea")

        self.app_dir = Path(__file__).resolve().parent
        self.output_dir = self.app_dir / "downloads"

        self.process = None
        self.stop_event = None
        self.log_queue: queue.Queue[str] = queue.Queue()

        self.results = []
        self.result_map = {}
        self.queue_tasks = []
        self.queue_comment_ids = set()
        self.api_busy = False
        self.local_api_handle = None
        self.local_api_lock = threading.Lock()

        self.service_var = tk.StringVar(value=DEFAULT_SERVICE_URL)
        self.token_var = tk.StringVar(value=DEFAULT_TOKEN)
        self.keyword_var = tk.StringVar(value="子夜归")
        self.format_var = tk.StringVar(value="xml")
        self.naming_rule_var = tk.StringVar(value=DEFAULT_NAMING_RULE)
        self.retry_var = tk.StringVar(value="5")
        self.concurrency_var = tk.StringVar(value="6")
        self.throttle_var = tk.StringVar(value="120")
        self.timeout_var = tk.StringVar(value="60000")
        self.status_var = tk.StringVar(value="状态: 待命")
        self.queue_count_var = tk.StringVar(value="队列: 0")

        self._build_ui()
        self._ensure_window_visible()
        self._bind_events()
        self._schedule_startup_workarea_fix()
        self._normalize_service_url(log_change=False)
        self.root.after(120, self._flush_logs)

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
        left, top, right, bottom = window_workarea.get_window_work_area(self.root)
        max_w = max(1, right - left)
        max_h = max(1, bottom - top)
        fit_min_w = min(min_w, max_w)
        fit_min_h = min(min_h, max_h)
        w = max(fit_min_w, min(pref_w, max_w))
        h = max(fit_min_h, min(pref_h, max_h))
        x = left + max(0, (max_w - w) // 2)
        y = top + max(0, (max_h - h) // 2)
        self.root.maxsize(max_w, max_h)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(fit_min_w, fit_min_h)

    def _ensure_window_visible(self):
        self.root.update_idletasks()
        work_area = window_workarea.get_window_work_area(self.root)
        left, top, right, bottom = work_area
        max_w = max(1, right - left)
        max_h = max(1, bottom - top)

        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        cur_w = self.root.winfo_width()
        cur_h = self.root.winfo_height()
        cur_x = self.root.winfo_x()
        cur_y = self.root.winfo_y()

        min_w = min(900, max_w)
        min_h = min(620, max_h)
        target_w = min(max_w, max(min_w, max(req_w, cur_w)))
        target_h = min(max_h, max(min_h, max(req_h, cur_h)))
        x, y, target_w, target_h = window_workarea.clamp_window_rect(
            x=cur_x,
            y=cur_y,
            width=target_w,
            height=target_h,
            work_area=work_area,
            min_width=min_w,
            min_height=min_h,
        )

        self.root.maxsize(max_w, max_h)
        self.root.minsize(min_w, min_h)
        target_geometry = f"{target_w}x{target_h}+{x}+{y}"
        current_geometry = (
            f"{max(1, self.root.winfo_width())}x{max(1, self.root.winfo_height())}"
            f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
        )
        if current_geometry != target_geometry:
            self.root.geometry(target_geometry)

    def _schedule_startup_workarea_fix(self):
        for delay in (120, 450, 1000):
            self.root.after(delay, self._auto_fix_window_workarea)

    def _auto_fix_window_workarea(self):
        if self.is_fullscreen:
            return
        try:
            state = self.root.state()
        except Exception:
            state = ""

        left, top, right, bottom = window_workarea.get_window_work_area(self.root)
        self.root.maxsize(max(1, right - left), max(1, bottom - top))
        if state == "zoomed":
            return
        self._ensure_window_visible()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 17), foreground="#0f766e")
        style.configure("Sub.TLabel", foreground="#64748b")
        style.configure("Accent.TButton", background="#0f766e", foreground="white", padding=(12, 8))
        style.map("Accent.TButton", background=[("active", "#0b5e58")])

        wrap = ttk.Frame(self.root, padding=12)
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=3)
        wrap.columnconfigure(1, weight=2)
        wrap.rowconfigure(2, weight=1)

        head = ttk.Frame(wrap)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(head, text="iDanmu_Speed Mini", style="Title.TLabel").pack(anchor="w")
        ttk.Label(head, text="搜索 -> 选来源 -> 加入全集 -> 开始下载", style="Sub.TLabel").pack(anchor="w")

        cfg = ttk.LabelFrame(wrap, text="连接", padding=10)
        cfg.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        cfg.columnconfigure(1, weight=1)
        cfg.columnconfigure(3, weight=1)

        ttk.Label(cfg, text="服务地址").grid(row=0, column=0, sticky="w")
        self.service_entry = ttk.Entry(cfg, textvariable=self.service_var)
        self.service_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 8))
        ttk.Button(cfg, text="解析地址", command=self._normalize_service_url).grid(row=0, column=4, sticky="w")

        ttk.Label(cfg, text="Token").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(cfg, textvariable=self.token_var, width=20).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        ttk.Label(cfg, text="输出目录").grid(row=1, column=2, sticky="e", pady=(6, 0))
        out_read = ttk.Entry(cfg, width=44)
        out_read.insert(0, str(self.output_dir))
        out_read.configure(state="readonly")
        out_read.grid(row=1, column=3, sticky="ew", padx=(8, 8), pady=(6, 0))
        ttk.Button(cfg, text="打开目录", command=self._open_output_dir).grid(row=1, column=4, sticky="w", pady=(6, 0))

        left = ttk.LabelFrame(wrap, text="搜索与来源", padding=10)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        search_row = ttk.Frame(left)
        search_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        search_row.columnconfigure(0, weight=1)
        ttk.Entry(search_row, textvariable=self.keyword_var).grid(row=0, column=0, sticky="ew")
        self.search_btn = ttk.Button(search_row, text="搜索", style="Accent.TButton", command=self.search)
        self.search_btn.grid(row=0, column=1, padx=(8, 0))

        action_row = ttk.Frame(left)
        action_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.add_full_btn = ttk.Button(action_row, text="加入所选来源全集", style="Accent.TButton", command=self.add_full_from_selected)
        self.add_full_btn.pack(side="left")

        results_wrap = ttk.Frame(left)
        results_wrap.grid(row=2, column=0, sticky="nsew")
        results_wrap.columnconfigure(0, weight=1)
        results_wrap.rowconfigure(0, weight=1)
        self.result_tree = ttk.Treeview(
            results_wrap,
            columns=("title", "source", "type", "animeId"),
            show="headings",
            selectmode="browse",
        )
        self.result_tree.heading("title", text="标题")
        self.result_tree.heading("source", text="来源")
        self.result_tree.heading("type", text="类型")
        self.result_tree.heading("animeId", text="animeId")
        self.result_tree.column("title", width=420, anchor="w")
        self.result_tree.column("source", width=95, anchor="center")
        self.result_tree.column("type", width=95, anchor="center")
        self.result_tree.column("animeId", width=95, anchor="center")
        self.result_tree.grid(row=0, column=0, sticky="nsew")
        ry = ttk.Scrollbar(results_wrap, orient="vertical", command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=ry.set)
        ry.grid(row=0, column=1, sticky="ns")

        right = ttk.LabelFrame(wrap, text="队列与执行", padding=10)
        right.grid(row=2, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        run_row = ttk.Frame(right)
        run_row.grid(row=0, column=0, sticky="ew")
        ttk.Label(run_row, textvariable=self.queue_count_var).pack(side="left")
        ttk.Label(run_row, text="格式").pack(side="left", padx=(12, 4))
        ttk.Combobox(run_row, state="readonly", values=["xml", "json"], width=7, textvariable=self.format_var).pack(side="left")
        ttk.Label(run_row, text="重试").pack(side="left", padx=(12, 4))
        ttk.Entry(run_row, width=5, textvariable=self.retry_var).pack(side="left")
        ttk.Label(run_row, text="并发").pack(side="left", padx=(12, 4))
        ttk.Entry(run_row, width=5, textvariable=self.concurrency_var).pack(side="left")
        ttk.Label(run_row, text="节流").pack(side="left", padx=(12, 4))
        ttk.Entry(run_row, width=8, textvariable=self.throttle_var).pack(side="left")
        ttk.Label(run_row, text="超时").pack(side="left", padx=(12, 4))
        ttk.Entry(run_row, width=8, textvariable=self.timeout_var).pack(side="left")

        naming_row = ttk.Frame(right)
        naming_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        naming_row.columnconfigure(1, weight=1)
        ttk.Label(naming_row, text="Naming Rule").grid(row=0, column=0, sticky="w")
        ttk.Entry(naming_row, textvariable=self.naming_rule_var).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(naming_row, text="tokens: {base} {name} {index:03d} {commentId}", foreground="#64748b").grid(
            row=1, column=1, sticky="w", pady=(2, 0)
        )

        queue_row = ttk.Frame(right)
        queue_row.grid(row=2, column=0, sticky="ew", pady=(8, 8))
        ttk.Button(queue_row, text="删除所选", command=self.remove_selected_queue).pack(side="left")
        ttk.Button(queue_row, text="清空队列", command=self.clear_queue).pack(side="left", padx=(8, 0))
        self.start_btn = ttk.Button(queue_row, text="开始下载", style="Accent.TButton", command=self.start_download)
        self.start_btn.pack(side="left", padx=(16, 0))
        self.stop_btn = ttk.Button(queue_row, text="停止", command=self.stop_download, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))

        queue_wrap = ttk.Frame(right)
        queue_wrap.grid(row=3, column=0, sticky="nsew")
        queue_wrap.columnconfigure(0, weight=1)
        queue_wrap.rowconfigure(0, weight=2)
        queue_wrap.rowconfigure(1, weight=3)

        self.queue_list = tk.Listbox(queue_wrap, activestyle="none")
        self.queue_list.grid(row=0, column=0, sticky="nsew", pady=(0, 8))

        self.log_text = tk.Text(
            queue_wrap,
            bg="#1f2933",
            fg="#dce4ea",
            relief="flat",
            font=("Consolas", 10),
            padx=8,
            pady=8,
        )
        self.log_text.insert("end", "准备就绪。\n")
        self.log_text.configure(state="disabled")
        self.log_text.grid(row=1, column=0, sticky="nsew")

        ttk.Label(wrap, textvariable=self.status_var, foreground="#64748b").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

    def _bind_events(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.service_entry.bind("<FocusOut>", lambda _e: self._normalize_service_url())
        self.service_entry.bind("<Return>", lambda _e: self._normalize_service_url())
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
        if not enabled:
            self.root.after(120, self._auto_fix_window_workarea)

    def _on_toggle_fullscreen(self, _event=None):
        self._set_fullscreen(not self.is_fullscreen)
        return "break"

    def _on_exit_fullscreen(self, _event=None):
        if self.is_fullscreen:
            self._set_fullscreen(False)
            return "break"
        return None

    def _append_log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_api_busy(self, busy: bool):
        self.api_busy = busy
        state = "disabled" if busy else "normal"
        self.search_btn.configure(state=state)
        self.add_full_btn.configure(state=state)
        self.root.config(cursor="watch" if busy else "")
        self.root.update_idletasks()

    def _run_api_task(self, start_status: str, fail_title: str, worker, on_success, show_error_popup: bool = True):
        if self.api_busy:
            return
        self.status_var.set(start_status)
        self._set_api_busy(True)

        def run():
            try:
                result = worker()
            except Exception as exc:
                self.root.after(0, lambda exc=exc: self._finish_api_error(fail_title, exc, show_error_popup))
                return
            self.root.after(0, lambda result=result: self._finish_api_success(on_success, result))

        threading.Thread(target=run, daemon=True).start()

    def _finish_api_success(self, on_success, result):
        try:
            on_success(result)
        finally:
            self._set_api_busy(False)

    def _finish_api_error(self, title: str, exc: Exception, show_error_popup: bool = True):
        self._set_api_busy(False)
        self.status_var.set("状态: 待命")
        self._append_log(f"{title}: {exc}\n")
        if show_error_popup:
            messagebox.showerror(title, str(exc))

    def _normalize_service_url(self, log_change=True):
        raw = self.service_var.get().strip()
        token = self.token_var.get().strip()
        if not raw:
            return None

        candidate = local_danmu_api.with_default_scheme(raw)
        parsed = url_parse.urlsplit(candidate)
        if not parsed.netloc:
            return None

        segments = [s for s in parsed.path.split("/") if s]
        auto_token = None
        if segments:
            tail = segments[-1]
            if not token:
                token = tail
                segments = segments[:-1]
                auto_token = tail
            elif token == tail:
                segments = segments[:-1]

        base_path = "/" + "/".join(segments) if segments else ""
        normalized = f"{parsed.scheme}://{parsed.netloc}{base_path}"

        if self.service_var.get().strip() != normalized:
            self.service_var.set(normalized)
        if self.token_var.get().strip() != token:
            self.token_var.set(token)
        if auto_token and log_change:
            self._append_log(f"已自动识别 token: {auto_token}\n")

        return normalized, token

    def _api_root(self):
        parsed = self._normalize_service_url(log_change=False)
        if not parsed:
            raise RuntimeError("服务地址不正确")
        base, token = parsed
        root = base.rstrip("/")
        if token:
            root += "/" + url_parse.quote(token)
        return root

    def _emit_local_api_log(self, text: str):
        self.log_queue.put(text)

    def _ensure_local_api_ready(self, base: str, token: str):
        if not local_danmu_api.is_local_base_url(base):
            return
        with self.local_api_lock:
            if self.local_api_handle is not None and self.local_api_handle.is_alive():
                return
            self.local_api_handle = local_danmu_api.ensure_local_api(
                base_url=base,
                token=token,
                log_fn=self._emit_local_api_log,
            )

    def _request_json(self, method, path, query=None, body=None, timeout=35):
        parsed = self._normalize_service_url(log_change=False)
        if not parsed:
            raise RuntimeError("服务地址不正确")
        base, token = parsed
        self._ensure_local_api_ready(base, token)
        root = base.rstrip("/")
        if token:
            root += "/" + url_parse.quote(token)
        try:
            retries = max(2, int(self.retry_var.get().strip()))
        except Exception:
            retries = 5

        try:
            return py_downloader.request_json_with_retry(
                api_root=root,
                path_name=path,
                method=method,
                query=query,
                body=body,
                timeout_ms=max(1000, int(timeout * 1000)),
                retries=retries,
                retry_delay_ms=2000,
                user_agent="iDanmu_Speed_Mini/2.0",
            )
        except py_downloader.HttpError as exc:
            detail = (exc.body or "").strip()
            raise RuntimeError(f"HTTP {exc.status}: {detail[:300]}") from exc
        except Exception as exc:
            raise RuntimeError(f"Request failed: {exc}") from exc

    def _source_of(self, anime):
        source = (anime.get("source") or "").strip()
        if source:
            return source
        title = anime.get("animeTitle", "")
        match = re.search(r"\bfrom\s+([a-zA-Z0-9_]+)\s*$", title, flags=re.I)
        return match.group(1).lower() if match else "unknown"

    def _short(self, text, n=70):
        text = (text or "").strip()
        return text if len(text) <= n else text[: n - 1] + "…"

    def search(self):
        keyword = self.keyword_var.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入关键词")
            return
        self._run_api_task(
            start_status="状态: 搜索中...",
            fail_title="搜索失败",
            worker=lambda: self._request_json("GET", "/api/v2/search/anime", query={"keyword": keyword}),
            on_success=lambda data, keyword=keyword: self._on_search_done(keyword, data),
            show_error_popup=False,
        )

    def _on_search_done(self, keyword, data):
        self.results = []
        self.result_map.clear()
        for anime in data.get("animes") or []:
            self.results.append(
                {
                    "animeId": anime.get("animeId"),
                    "title": anime.get("animeTitle", ""),
                    "source": self._source_of(anime),
                    "type": anime.get("typeDescription") or anime.get("type") or "",
                }
            )

        for iid in self.result_tree.get_children():
            self.result_tree.delete(iid)
        for idx, item in enumerate(self.results, start=1):
            iid = f"r-{idx}-{item['animeId']}"
            self.result_map[iid] = item
            self.result_tree.insert(
                "",
                "end",
                iid=iid,
                values=(self._short(item["title"], 72), item["source"], self._short(item["type"], 18), item["animeId"]),
            )
        self.status_var.set(f"状态: 搜索完成，共 {len(self.results)} 条")
        self._append_log(f"搜索完成: {keyword} -> {len(self.results)} 条\n")

    def _selected_result(self):
        sel = self.result_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个来源")
            return None
        return self.result_map.get(sel[0])

    def _make_tasks_from_full_season(self, anime, episodes):
        tasks = []
        clean_title = re.sub(r"\s*from\s+\w+\s*$", "", anime["title"], flags=re.I).strip() or "unknown"
        fmt = self.format_var.get().strip() or "xml"
        for i, ep in enumerate(episodes, start=1):
            cid = ep.get("episodeId")
            if cid is None:
                continue
            ep_no = str(ep.get("episodeNumber") or i)
            ep_title = ep.get("episodeTitle") or f"第{ep_no}集"
            name = self._short(f"{clean_title}-第{ep_no}集-{ep_title}", 72)
            tasks.append({"name": name, "commentId": int(cid) if str(cid).isdigit() else cid, "format": fmt})
        return tasks

    def add_full_from_selected(self):
        anime = self._selected_result()
        if not anime:
            return
        self._run_api_task(
            start_status="状态: 正在加载全集...",
            fail_title="加入失败",
            worker=lambda: self._request_json("GET", f"/api/v2/bangumi/{anime['animeId']}"),
            on_success=lambda data, anime=anime: self._on_add_full_done(anime, data),
        )

    def _on_add_full_done(self, anime, data):
        episodes = (data.get("bangumi") or {}).get("episodes") or []
        tasks = self._make_tasks_from_full_season(anime, episodes)
        added = 0
        skipped = 0
        for task in tasks:
            cid_key = str(task.get("commentId"))
            if cid_key in self.queue_comment_ids:
                skipped += 1
                continue
            self.queue_comment_ids.add(cid_key)
            self.queue_tasks.append(task)
            self.queue_list.insert("end", f"{task['name']}  [cid={task['commentId']}]")
            added += 1
        self.queue_count_var.set(f"队列: {len(self.queue_tasks)}")
        self.status_var.set(f"状态: 已加入 {added} 条，跳过重复 {skipped} 条")
        self._append_log(f"加入来源全集: {anime['source']} / animeId={anime['animeId']} -> +{added}, 重复跳过 {skipped}\n")

    def remove_selected_queue(self):
        selected = list(self.queue_list.curselection())
        if not selected:
            return
        new_tasks = []
        self.queue_list.delete(0, "end")
        for i, task in enumerate(self.queue_tasks):
            if i in selected:
                continue
            new_tasks.append(task)
            self.queue_list.insert("end", f"{task['name']}  [cid={task.get('commentId', '-')}]")
        self.queue_tasks = new_tasks
        self.queue_comment_ids = {str(t.get("commentId")) for t in self.queue_tasks if t.get("commentId") is not None}
        self.queue_count_var.set(f"队列: {len(self.queue_tasks)}")

    def clear_queue(self):
        self.queue_tasks.clear()
        self.queue_comment_ids.clear()
        self.queue_list.delete(0, "end")
        self.queue_count_var.set("队列: 0")

    def _set_running(self, running: bool):
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        self.status_var.set("状态: 下载中..." if running else "状态: 待命")

    def start_download(self):
        if self.process is not None:
            return
        if not self.queue_tasks:
            messagebox.showwarning("提示", "下载队列为空")
            return

        try:
            parsed = self._normalize_service_url(log_change=False)
            if not parsed:
                raise RuntimeError("服务地址无效")
            base, token = parsed
            concurrency = max(1, int(self.concurrency_var.get().strip()))
            retries = max(0, int(self.retry_var.get().strip()))
            throttle = max(0, int(self.throttle_var.get().strip()))
            timeout = max(1000, int(self.timeout_var.get().strip()))
            fmt = self.format_var.get().strip() or "xml"
            naming_rule = self.naming_rule_var.get().strip() or DEFAULT_NAMING_RULE
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._append_log("\n=== 开始下载 ===\n")
        self._append_log(
            f"params: base={base}, token={'***' if token else '(none)'}, format={fmt}, naming_rule={naming_rule}, "
            f"concurrency={concurrency}, retries={retries}, throttle_ms={throttle}, timeout_ms={timeout}\n\n"
        )
        self._set_running(True)
        self.stop_event = threading.Event()

        def worker():
            try:
                exit_code = py_downloader.run_download(
                    {
                        "base_url": base,
                        "token": token,
                        "output": str(self.output_dir),
                        "format": fmt,
                        "naming_rule": naming_rule,
                        "concurrency": concurrency,
                        "retries": retries,
                        "throttle_ms": throttle,
                        "timeout_ms": timeout,
                    },
                    tasks_override=self.queue_tasks,
                    log_fn=lambda text: self.log_queue.put(text),
                    is_cancelled=self.stop_event.is_set,
                )
                self.log_queue.put(f"\n=== 下载结束，退出码: {exit_code} ===\n")
            except Exception as exc:
                self.log_queue.put(f"\n执行失败: {exc}\n")
            finally:
                self.process = None
                self.stop_event = None
                self.log_queue.put("__DONE__")

        self.process = threading.Thread(target=worker, daemon=True)
        self.process.start()

    def stop_download(self):
        if self.process is None:
            return
        if self.stop_event is not None and not self.stop_event.is_set():
            self.stop_event.set()
            self._append_log("\n已请求停止任务（等待当前请求完成）...\n")

    def _open_output_dir(self):
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.output_dir))
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def _flush_logs(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__DONE__":
                    self._set_running(False)
                else:
                    self._append_log(msg)
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._flush_logs)

    def _on_close(self):
        if self.process is not None:
            ok = messagebox.askyesno("确认退出", "当前任务仍在运行，确定退出吗？")
            if not ok:
                return
            if self.stop_event is not None:
                self.stop_event.set()
        with self.local_api_lock:
            if self.local_api_handle is not None and self.local_api_handle.started_by_tool:
                self.local_api_handle.stop()
            self.local_api_handle = None
        self.root.destroy()


def main():
    _enable_windows_dpi_awareness()
    root = tk.Tk()
    MiniDanmuGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()


