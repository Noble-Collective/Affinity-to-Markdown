#!/usr/bin/env python3
"""
main.py — Entry point for the Affinity-PDF-Markdown Converter.
"""

import tkinter as tk
from gui import ConverterApp
from config import APP_NAME


def main():
    root = tk.Tk()
    root.title(APP_NAME)
    root.update_idletasks()
    w, h = 760, 640
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    app = ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
