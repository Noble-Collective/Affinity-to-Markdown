"""
gui.py — tkinter GUI for the Affinity-PDF-Markdown Converter.
"""

import os, queue, subprocess, sys, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from config import APP_NAME, APP_VERSION, get_available_templates, check_marker_pdf_dir, check_models_downloaded, IS_WINDOWS
from pipeline import PipelineRunner
from calibrate import CalibrateRunner

MSG_LOG = "log"
MSG_PROGRESS = "progress"
MSG_DONE = "done"
MSG_UPDATE = "update"
_UPDATE_CHECK_INTERVAL_MS = 30_000
_NEW_BOOK_SENTINEL = "-- New book --"


class ConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("760x640")
        self.root.minsize(640, 520)
        self._queue = queue.Queue()
        self._runner = None
        self._calibrator = None
        self._last_output = None
        self._update_info = None
        self._update_banner_shown = False
        self._mode = "convert"
        self._build_ui()
        self._start_polling()
        self.root.after(100, self._startup_checks)

    def _build_ui(self):
        style = ttk.Style()
        if IS_WINDOWS:
            try: style.theme_use("vista")
            except tk.TclError: style.theme_use("clam")
        else:
            try: style.theme_use("aqua")
            except tk.TclError: style.theme_use("clam")

        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)
        self._main = main

        self.update_frame = tk.Frame(main, bg="#2d5a27", padx=8, pady=6)
        self.update_label = tk.Label(self.update_frame, text="", bg="#2d5a27", fg="white",
            font=("Segoe UI" if IS_WINDOWS else "Helvetica", 10))
        self.update_label.pack(side="left", fill="x", expand=True)
        self.update_btn = tk.Button(self.update_frame, text="Update Now", command=self._on_update,
            bg="#4a8c3f", fg="white", relief="flat", padx=12, pady=2)
        self.update_btn.pack(side="right", padx=(8, 0))

        row = 1
        ttk.Label(main, text="PDF file:").grid(row=row, column=0, sticky="w", pady=(0,4))
        self.pdf_var = tk.StringVar()
        ttk.Entry(main, textvariable=self.pdf_var, width=55).grid(row=row, column=1, sticky="ew", pady=(0,4), padx=(4,4))
        ttk.Button(main, text="Browse", command=self._browse_pdf).grid(row=row, column=2, pady=(0,4))

        row += 1
        ttk.Label(main, text="Template:").grid(row=row, column=0, sticky="w", pady=(0,4))
        templates = get_available_templates()
        templates.append(_NEW_BOOK_SENTINEL)
        self.template_var = tk.StringVar(value=templates[0] if len(templates) > 1 else "homestead")
        self.template_combo = ttk.Combobox(main, textvariable=self.template_var, values=templates, state="readonly", width=30)
        self.template_combo.grid(row=row, column=1, sticky="w", pady=(0,4), padx=(4,4))
        self.template_combo.bind("<<ComboboxSelected>>", self._on_template_change)

        row += 1
        self._output_row = row
        self.output_label = ttk.Label(main, text="Output:")
        self.output_label.grid(row=row, column=0, sticky="w", pady=(0,4))
        self.output_var = tk.StringVar()
        self.output_entry = ttk.Entry(main, textvariable=self.output_var, width=55)
        self.output_entry.grid(row=row, column=1, sticky="ew", pady=(0,4), padx=(4,4))
        self.output_browse = ttk.Button(main, text="Browse", command=self._browse_output)
        self.output_browse.grid(row=row, column=2, pady=(0,4))

        self.bookname_label = ttk.Label(main, text="Book name:")
        self.bookname_var = tk.StringVar()
        self.bookname_entry = ttk.Entry(main, textvariable=self.bookname_var, width=55)

        row += 1
        self._mode_row = row
        self.mode_frame = ttk.LabelFrame(main, text="Mode", padding=6)
        self.mode_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(4,4))
        self.mode_var = tk.StringVar(value="full")
        ttk.Radiobutton(self.mode_frame, text="Full Conversion (Marker ML + post-processing)", variable=self.mode_var, value="full", command=self._on_mode_change).pack(anchor="w")
        ttk.Radiobutton(self.mode_frame, text="Post-process Only (from existing .raw.md)", variable=self.mode_var, value="postprocess", command=self._on_mode_change).pack(anchor="w")

        self.info_frame = tk.Frame(main, bg="#E6F1FB", padx=10, pady=8)
        self.info_text = tk.Label(self.info_frame, text=(
            "Extracts everything Claude needs to build a template for this book.\n"
            "Takes ~15 min. Outputs 3 files to upload to Claude.\n"
            "\u2022 Font analysis (~30s)   \u2022 Marker extraction (~10-15 min)   \u2022 PyMuPDF spans (~1-2 min)"
        ), bg="#E6F1FB", fg="#0C447C", font=("Segoe UI" if IS_WINDOWS else "Helvetica", 9), justify="left")
        self.info_text.pack(anchor="w")

        row += 1
        self.raw_frame = ttk.Frame(main)
        self.raw_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0,4))
        ttk.Label(self.raw_frame, text="Raw .md:").pack(side="left")
        self.raw_var = tk.StringVar()
        ttk.Entry(self.raw_frame, textvariable=self.raw_var, width=50).pack(side="left", fill="x", expand=True, padx=(4,4))
        ttk.Button(self.raw_frame, text="Browse", command=self._browse_raw).pack(side="left")
        self.raw_frame.grid_remove()

        row += 1
        self._opts_row = row
        self.opts_frame = ttk.Frame(main)
        self.opts_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0,4))
        ttk.Label(self.opts_frame, text="Page range:").pack(side="left")
        self.pagerange_var = tk.StringVar()
        ttk.Entry(self.opts_frame, textvariable=self.pagerange_var, width=14).pack(side="left", padx=(4,12))
        ttk.Label(self.opts_frame, text="(optional, e.g. 37-84)").pack(side="left")
        self.saveraw_var = tk.BooleanVar(value=False)
        self.saveraw_check = ttk.Checkbutton(self.opts_frame, text="Save raw Marker output", variable=self.saveraw_var)
        self.saveraw_check.pack(side="right")

        row += 1
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(main, variable=self.progress_var, maximum=1.0, length=400).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8,2))
        row += 1
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.status_var, foreground="gray").grid(row=row, column=0, columnspan=3, sticky="w", pady=(0,4))

        row += 1
        log_frame = ttk.LabelFrame(main, text="Log", padding=4)
        log_frame.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(4,4))
        main.rowconfigure(row, weight=1)
        main.columnconfigure(1, weight=1)
        self.log_text = tk.Text(log_frame, height=12, wrap="word", state="disabled",
            font=("Consolas" if IS_WINDOWS else "Menlo", 9), bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4")
        sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

        row += 1
        btn = ttk.Frame(main)
        btn.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(4,0))
        self.open_folder_btn = ttk.Button(btn, text="Open folder", command=self._open_folder, state="disabled")
        self.open_folder_btn.pack(side="left", padx=(0,4))
        self.open_output_btn = ttk.Button(btn, text="Open output", command=self._open_output, state="disabled")
        self.open_output_btn.pack(side="left", padx=(0,8))
        self.convert_btn = ttk.Button(btn, text="Convert", command=self._on_action)
        self.convert_btn.pack(side="right", padx=(4,0))
        self.cancel_btn = ttk.Button(btn, text="Cancel", command=self._on_cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=(0,4))

    def _on_template_change(self, event=None):
        if self.template_var.get() == _NEW_BOOK_SENTINEL:
            self._switch_to_calibrate()
        else:
            self._switch_to_convert()

    def _switch_to_calibrate(self):
        self._mode = "calibrate"
        self.output_label.grid_remove()
        self.output_entry.grid_remove()
        self.output_browse.grid_remove()
        self.mode_frame.grid_remove()
        self.raw_frame.grid_remove()
        self.opts_frame.grid_remove()
        self.open_output_btn.configure(state="disabled")
        self.bookname_label.grid(row=self._output_row, column=0, sticky="w", pady=(0,4))
        self.bookname_entry.grid(row=self._output_row, column=1, sticky="ew", pady=(0,4), padx=(4,4))
        self.info_frame.grid(row=self._mode_row, column=0, columnspan=3, sticky="ew", pady=(4,4))
        self.convert_btn.configure(text="Calibrate")
        pdf = self.pdf_var.get().strip()
        if pdf and not self.bookname_var.get():
            self.bookname_var.set(Path(pdf).stem.lower().replace(" ", "_").replace("-", "_")[:30])

    def _switch_to_convert(self):
        self._mode = "convert"
        self.bookname_label.grid_remove()
        self.bookname_entry.grid_remove()
        self.info_frame.grid_remove()
        self.output_label.grid(row=self._output_row, column=0, sticky="w", pady=(0,4))
        self.output_entry.grid(row=self._output_row, column=1, sticky="ew", pady=(0,4), padx=(4,4))
        self.output_browse.grid(row=self._output_row, column=2, pady=(0,4))
        self.mode_frame.grid(row=self._mode_row, column=0, columnspan=3, sticky="ew", pady=(4,4))
        self.opts_frame.grid(row=self._opts_row, column=0, columnspan=3, sticky="ew", pady=(0,4))
        self._on_mode_change()
        self.convert_btn.configure(text="Convert")

    def _on_mode_change(self):
        if self.mode_var.get() == "postprocess":
            self.raw_frame.grid()
            self.saveraw_check.configure(state="disabled")
        else:
            self.raw_frame.grid_remove()
            self.saveraw_check.configure(state="normal")

    def _startup_checks(self):
        if not check_marker_pdf_dir():
            messagebox.showwarning("Missing Pipeline",
                "Could not find marker-pdf/run.py.\n\nMake sure this app's folder is inside the Affinity-to-Markdown repo alongside marker-pdf/.")
            return
        if not check_models_downloaded():
            self._log_append("NOTE: ML models not found. They will download on first run (~500MB).")
        from updater import has_local_updates, get_installed_version
        if has_local_updates():
            self._log_append(f"Pipeline update v{get_installed_version()} installed.")
        templates = get_available_templates()
        if templates:
            self._log_append(f"Templates: {', '.join(templates)}")
        self._log_append("Ready.")
        self._schedule_update_check()

    def _schedule_update_check(self):
        from updater import check_for_updates_async
        check_for_updates_async(lambda info: self._queue.put((MSG_UPDATE, info)))
        self.root.after(_UPDATE_CHECK_INTERVAL_MS, self._schedule_update_check)

    def _show_update_banner(self, info):
        self._update_info = info
        self._update_banner_shown = True
        n = len(info.files)
        self.update_label.configure(text=f"Update v{info.remote_version} available \u2014 {info.notes} ({n} files)")
        self.update_frame.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0,8), in_=self._main)

    def _on_update(self):
        if not self._update_info: return
        info = self._update_info
        self.update_btn.configure(state="disabled", text="Updating...")
        self._log_append(f"Downloading update v{info.remote_version}...")
        import threading
        from updater import download_updates
        def _do():
            def _prog(cur, tot, fn):
                self._queue.put((MSG_LOG, f"  Downloading {fn} ({cur+1}/{tot})..."))
            ok, msg = download_updates(info.files, info.remote_version, info.notes, _prog)
            self._queue.put((MSG_LOG, msg))
            if ok:
                self._queue.put((MSG_LOG, "Update complete! New pipeline used on next conversion."))
                self.root.after(0, self._hide_update_banner)
            else:
                self.root.after(0, lambda: self.update_btn.configure(state="normal", text="Retry"))
        threading.Thread(target=_do, daemon=True).start()

    def _hide_update_banner(self):
        self.update_frame.grid_remove()
        self.update_btn.configure(state="normal", text="Update Now")
        self._update_banner_shown = False

    def _browse_pdf(self):
        path = filedialog.askopenfilename(title="Select PDF file", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if path:
            self.pdf_var.set(path)
            if not self.output_var.get():
                self.output_var.set(str(Path(path).with_suffix(".md")))
            if self._mode == "calibrate" and not self.bookname_var.get():
                self.bookname_var.set(Path(path).stem.lower().replace(" ", "_").replace("-", "_")[:30])

    def _browse_output(self):
        path = filedialog.asksaveasfilename(title="Save output as", defaultextension=".md", filetypes=[("Markdown files", "*.md"), ("All files", "*.*")])
        if path: self.output_var.set(path)

    def _browse_raw(self):
        path = filedialog.askopenfilename(title="Select raw .md file", filetypes=[("Markdown files", "*.md *.raw.md"), ("All files", "*.*")])
        if path: self.raw_var.set(path)

    def _on_action(self):
        if self._mode == "calibrate": self._on_calibrate()
        else: self._on_convert()

    def _on_convert(self):
        pdf_path = self.pdf_var.get().strip()
        if not pdf_path or not Path(pdf_path).exists():
            messagebox.showerror("Error", "Please select a valid PDF file."); return
        output_path = self.output_var.get().strip()
        if not output_path:
            messagebox.showerror("Error", "Please specify an output path."); return
        template = self.template_var.get()
        page_range = self.pagerange_var.get().strip()
        mode = self.mode_var.get()
        if mode == "postprocess":
            raw_path = self.raw_var.get().strip()
            if not raw_path or not Path(raw_path).exists():
                messagebox.showerror("Error", "Post-process mode requires a raw .md file."); return
            if Path(output_path).resolve() == Path(raw_path).resolve():
                output_path = str(Path(raw_path).with_stem(Path(raw_path).stem + "_processed"))
                self.output_var.set(output_path)
        self._start_run()
        self._runner = PipelineRunner(
            log_callback=lambda msg: self._queue.put((MSG_LOG, msg)),
            progress_callback=lambda frac, label: self._queue.put((MSG_PROGRESS, frac, label)),
            done_callback=lambda ok, path, err: self._queue.put((MSG_DONE, ok, path, err)),
        )
        if mode == "full":
            self._runner.start_full(pdf_path, template, output_path, page_range, save_raw=self.saveraw_var.get())
        else:
            self._runner.start_postprocess(self.raw_var.get().strip(), pdf_path, template, output_path, page_range)

    def _on_calibrate(self):
        pdf_path = self.pdf_var.get().strip()
        if not pdf_path or not Path(pdf_path).exists():
            messagebox.showerror("Error", "Please select a valid PDF file."); return
        book_name = self.bookname_var.get().strip()
        if not book_name:
            messagebox.showerror("Error", "Please enter a book name."); return
        self._start_run()
        self._calibrator = CalibrateRunner(
            log_callback=lambda msg: self._queue.put((MSG_LOG, msg)),
            progress_callback=lambda frac, label: self._queue.put((MSG_PROGRESS, frac, label)),
            done_callback=lambda ok, path, err: self._queue.put((MSG_DONE, ok, path, err)),
        )
        self._calibrator.start(pdf_path, book_name)

    def _start_run(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.progress_var.set(0.0)
        self.status_var.set("Starting...")
        self._last_output = None
        self.convert_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.open_output_btn.configure(state="disabled")
        self.open_folder_btn.configure(state="disabled")

    def _on_cancel(self):
        if self._runner and self._runner.is_running: self._runner.cancel()
        if self._calibrator and self._calibrator.is_running: self._calibrator.cancel()
        self.status_var.set("Cancelling...")

    def _start_polling(self): self._poll_queue()

    def _poll_queue(self):
        try:
            while True: self._handle_message(self._queue.get_nowait())
        except queue.Empty: pass
        self.root.after(50, self._poll_queue)

    def _handle_message(self, msg):
        kind = msg[0]
        if kind == MSG_LOG:
            self._log_append(msg[1])
        elif kind == MSG_PROGRESS:
            self.progress_var.set(msg[1])
            self.status_var.set(msg[2])
        elif kind == MSG_DONE:
            _, success, output_path, error = msg
            self.convert_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            if success and output_path:
                self._last_output = output_path
                self.open_folder_btn.configure(state="normal")
                if self._mode == "convert":
                    self.open_output_btn.configure(state="normal")
                    self.status_var.set(f"Done! Output: {Path(output_path).name}")
                else:
                    self.status_var.set(f"Calibration complete! Folder: {Path(output_path).name}")
                self.progress_var.set(1.0)
            elif error == "Cancelled":
                self.status_var.set("Cancelled.")
                self.progress_var.set(0.0)
            else:
                self.status_var.set(f"Failed: {error}")
                messagebox.showerror("Failed", f"Error:\n\n{error}")
        elif kind == MSG_UPDATE:
            info = msg[1]
            if info.available and not self._update_banner_shown:
                self._log_append(f"Update v{info.remote_version} available: {info.notes}")
                self._show_update_banner(info)

    def _log_append(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _open_output(self):
        if self._last_output and Path(self._last_output).exists():
            if IS_WINDOWS: os.startfile(self._last_output)
            else: subprocess.run(["open", self._last_output])

    def _open_folder(self):
        if self._last_output:
            target = Path(self._last_output)
            folder = str(target if target.is_dir() else target.parent)
            if IS_WINDOWS: os.startfile(folder)
            else: subprocess.run(["open", folder])
