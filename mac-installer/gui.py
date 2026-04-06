"""
gui.py — tkinter GUI for the Affinity-PDF-Markdown Converter.
"""

import os
import queue
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional

from config import APP_NAME, APP_VERSION, get_available_templates, check_marker_pdf_dir, check_models_downloaded, IS_WINDOWS
from pipeline import PipelineRunner

MSG_LOG = "log"
MSG_PROGRESS = "progress"
MSG_DONE = "done"


class ConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("760x640")
        self.root.minsize(640, 520)
        self._queue = queue.Queue()
        self._runner = None
        self._last_output = None
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

        # PDF file picker
        row = 0
        ttk.Label(main, text="PDF File:").grid(row=row, column=0, sticky="w", pady=(0,4))
        self.pdf_var = tk.StringVar()
        ttk.Entry(main, textvariable=self.pdf_var, width=55).grid(row=row, column=1, sticky="ew", pady=(0,4), padx=(4,4))
        ttk.Button(main, text="Browse", command=self._browse_pdf).grid(row=row, column=2, pady=(0,4))

        # Template
        row += 1
        ttk.Label(main, text="Template:").grid(row=row, column=0, sticky="w", pady=(0,4))
        templates = get_available_templates()
        self.template_var = tk.StringVar(value=templates[0] if templates else "homestead")
        ttk.Combobox(main, textvariable=self.template_var, values=templates, state="readonly", width=30).grid(row=row, column=1, sticky="w", pady=(0,4), padx=(4,4))

        # Output
        row += 1
        ttk.Label(main, text="Output:").grid(row=row, column=0, sticky="w", pady=(0,4))
        self.output_var = tk.StringVar()
        ttk.Entry(main, textvariable=self.output_var, width=55).grid(row=row, column=1, sticky="ew", pady=(0,4), padx=(4,4))
        ttk.Button(main, text="Browse", command=self._browse_output).grid(row=row, column=2, pady=(0,4))

        # Mode
        row += 1
        mode_frame = ttk.LabelFrame(main, text="Mode", padding=6)
        mode_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(4,4))
        self.mode_var = tk.StringVar(value="full")
        ttk.Radiobutton(mode_frame, text="Full Conversion (Marker ML + post-processing)", variable=self.mode_var, value="full", command=self._on_mode_change).pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="Post-process Only (from existing .raw.md)", variable=self.mode_var, value="postprocess", command=self._on_mode_change).pack(anchor="w")

        # Raw .md picker
        row += 1
        self.raw_frame = ttk.Frame(main)
        self.raw_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0,4))
        ttk.Label(self.raw_frame, text="Raw .md:").pack(side="left")
        self.raw_var = tk.StringVar()
        ttk.Entry(self.raw_frame, textvariable=self.raw_var, width=50).pack(side="left", fill="x", expand=True, padx=(4,4))
        ttk.Button(self.raw_frame, text="Browse", command=self._browse_raw).pack(side="left")
        self.raw_frame.grid_remove()

        # Options
        row += 1
        opts = ttk.Frame(main)
        opts.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0,4))
        ttk.Label(opts, text="Page Range:").pack(side="left")
        self.pagerange_var = tk.StringVar()
        ttk.Entry(opts, textvariable=self.pagerange_var, width=14).pack(side="left", padx=(4,12))
        ttk.Label(opts, text="(optional, e.g. 37-84)").pack(side="left")
        self.saveraw_var = tk.BooleanVar(value=False)
        self.saveraw_check = ttk.Checkbutton(opts, text="Save raw Marker output", variable=self.saveraw_var)
        self.saveraw_check.pack(side="right")

        # Progress
        row += 1
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(main, variable=self.progress_var, maximum=1.0, length=400).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8,2))
        row += 1
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.status_var, foreground="gray").grid(row=row, column=0, columnspan=3, sticky="w", pady=(0,4))

        # Log
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

        # Buttons
        row += 1
        btn = ttk.Frame(main)
        btn.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(4,0))
        self.convert_btn = ttk.Button(btn, text="Convert", command=self._on_convert)
        self.convert_btn.pack(side="left", padx=(0,8))
        self.cancel_btn = ttk.Button(btn, text="Cancel", command=self._on_cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(0,8))
        self.open_output_btn = ttk.Button(btn, text="Open Output", command=self._open_output, state="disabled")
        self.open_output_btn.pack(side="right", padx=(8,0))
        self.open_folder_btn = ttk.Button(btn, text="Open Folder", command=self._open_folder, state="disabled")
        self.open_folder_btn.pack(side="right")

    def _startup_checks(self):
        if not check_marker_pdf_dir():
            messagebox.showwarning("Missing Pipeline",
                "Could not find marker-pdf/run.py.\n\nMake sure this app's folder is inside the Affinity-to-Markdown repo alongside marker-pdf/.")
            return
        if not check_models_downloaded():
            self._log_append("NOTE: ML models not found in local cache. They will be downloaded on first full conversion (~500MB). This is a one-time download.")
        templates = get_available_templates()
        if templates:
            self._log_append(f"Templates available: {', '.join(templates)}")
        else:
            self._log_append("WARNING: No templates found in marker-pdf/templates/")
        self._log_append("Ready.")

    def _on_mode_change(self):
        if self.mode_var.get() == "postprocess":
            self.raw_frame.grid()
            self.saveraw_check.configure(state="disabled")
        else:
            self.raw_frame.grid_remove()
            self.saveraw_check.configure(state="normal")

    def _browse_pdf(self):
        path = filedialog.askopenfilename(title="Select PDF file", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if path:
            self.pdf_var.set(path)
            if not self.output_var.get():
                self.output_var.set(str(Path(path).with_suffix(".md")))

    def _browse_output(self):
        path = filedialog.asksaveasfilename(title="Save output as", defaultextension=".md", filetypes=[("Markdown files", "*.md"), ("All files", "*.*")])
        if path: self.output_var.set(path)

    def _browse_raw(self):
        path = filedialog.askopenfilename(title="Select raw Marker .md file", filetypes=[("Markdown files", "*.md *.raw.md"), ("All files", "*.*")])
        if path: self.raw_var.set(path)

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

        self._runner = PipelineRunner(
            log_callback=lambda msg: self._queue.put((MSG_LOG, msg)),
            progress_callback=lambda frac, label: self._queue.put((MSG_PROGRESS, frac, label)),
            done_callback=lambda ok, path, err: self._queue.put((MSG_DONE, ok, path, err)),
        )
        if mode == "full":
            self._runner.start_full(pdf_path, template, output_path, page_range, save_raw=self.saveraw_var.get())
        else:
            self._runner.start_postprocess(self.raw_var.get().strip(), pdf_path, template, output_path, page_range)

    def _on_cancel(self):
        if self._runner and self._runner.is_running:
            self._runner.cancel()
            self.status_var.set("Cancelling...")

    def _start_polling(self):
        self._poll_queue()

    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        self.root.after(50, self._poll_queue)

    def _handle_message(self, msg):
        kind = msg[0]
        if kind == MSG_LOG:
            self._log_append(msg[1])
        elif kind == MSG_PROGRESS:
            _, frac, label = msg
            self.progress_var.set(frac)
            self.status_var.set(label)
        elif kind == MSG_DONE:
            _, success, output_path, error = msg
            self.convert_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            if success and output_path:
                self._last_output = output_path
                self.open_output_btn.configure(state="normal")
                self.open_folder_btn.configure(state="normal")
                self.status_var.set(f"Done! Output: {Path(output_path).name}")
                self.progress_var.set(1.0)
            elif error == "Cancelled":
                self.status_var.set("Cancelled.")
                self.progress_var.set(0.0)
            else:
                self.status_var.set(f"Failed: {error}")
                messagebox.showerror("Conversion Failed", f"Error:\n\n{error}")

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
            folder = str(Path(self._last_output).parent)
            if IS_WINDOWS: os.startfile(folder)
            else: subprocess.run(["open", folder])
