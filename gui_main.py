import sys
import os
import ctypes
import subprocess
import tkinter as tk
from tkinter import messagebox, Menu
import threading

# Safe dependency check compatible with 'uv' environments
try:
    import customtkinter as ctk
except ImportError:
    try:
        temp_root = tk.Tk()
        temp_root.withdraw()
        has_tk = True
    except:
        has_tk = False

    msg = ("The 'customtkinter' package is missing.\n\n"
           "If using 'uv', run:\n    uv add customtkinter\n\n"
           "If using pip, run:\n    pip install customtkinter")

    if has_tk:
        messagebox.showerror("Dependency Missing", msg)
        temp_root.destroy()
    else:
        print(f"ERROR: {msg}")

    sys.exit(1)

import backend
import storage_ops

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tw = None
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        if not self.text: return
        # STRICT CHECK: Prevent creating multiple windows or creating if already exists
        if self.tw:
            return

        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 25
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tw, text=self.text, justify='left',
                         background="#2b2b2b", foreground="white",
                         relief='solid', borderwidth=1, font=("Arial", 10), padx=8, pady=5)
        label.pack()

    def leave(self, event=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None


class StorageApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Windows Storage Spaces Manager")
        self.geometry("1700x950")

        self.grid_columnconfigure(0, weight=5)
        self.grid_columnconfigure(1, weight=3)
        self.grid_columnconfigure(2, weight=3)

        self.grid_rowconfigure(0, weight=4)
        self.grid_rowconfigure(1, weight=1)

        self.pool_name_var = ctk.StringVar()
        self.pool_name_var.trace_add("write", self.validate_state)
        self.vd_name_var = ctk.StringVar()
        self.vd_name_var.trace_add("write", self.validate_state)
        self.selected_pool_var = ctk.StringVar(value="")
        self.selected_pool_var.trace_add("write", self.on_pool_change)
        self.selected_vd_var = ctk.StringVar(value="")
        self.selected_vd_var.trace_add("write", self.validate_state)

        self.disk_checkboxes = []
        self.selected_context_disk_obj = None

        self.setup_left_pane()
        self.setup_middle_pane()
        self.setup_right_pane()
        self.setup_bottom_pane()

        backend.log_callback = self.write_log
        self.refresh_data()

    def write_log(self, message):
        self.log_box.configure(state="normal")
        if message.startswith("[CMD]"):
            self.log_box.insert("end", message + "\n", "cmd_color")
        elif message.startswith("[OUT]"):
            self.log_box.insert("end", message + "\n", "out_color")
        elif message.startswith("[ERR]"):
            self.log_box.insert("end", message + "\n", "err_color")
        else:
            self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def setup_left_pane(self):
        left_frame = ctk.CTkFrame(self)
        left_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")

        ctk.CTkLabel(left_frame, text="1. Physical Disks", font=("Arial", 16, "bold")).pack(pady=10)

        btn_refresh = ctk.CTkButton(left_frame, text="Refresh Hardware", command=self.refresh_data)
        btn_refresh.pack(pady=5)

        header_frame = ctk.CTkFrame(left_frame, fg_color="#343638", corner_radius=0)
        header_frame.pack(padx=5, pady=(5, 0), fill="x")

        self.table_font = ("Consolas", 11)
        self.table_layout = [
            ("", 30), ("Num", 40), ("Name", 180), ("Media", 70),
            ("Size (GB)", 80), ("Usage", 80), ("Status", 70), ("Can Pool", 60)
        ]

        for text, width in self.table_layout:
            lbl = ctk.CTkLabel(header_frame, text=text, width=width, anchor="w", font=("Arial", 11, "bold"))
            lbl.pack(side="left", padx=2)

        self.disk_container = ctk.CTkScrollableFrame(left_frame, fg_color="#212121", corner_radius=0)
        self.disk_container.pack(padx=5, pady=(0, 10), fill="both", expand=True)

        self.context_menu = Menu(self, tearoff=0, bg="#2b2b2b", fg="white", activebackground="#1f538d")
        self.context_menu.add_command(label="Force MediaType: SCM (NVMe)",
                                      command=lambda: self.change_media_type("SCM"))
        self.context_menu.add_command(label="Force MediaType: SSD", command=lambda: self.change_media_type("SSD"))
        self.context_menu.add_command(label="Force MediaType: HDD", command=lambda: self.change_media_type("HDD"))

        pool_ctrl_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        pool_ctrl_frame.pack(padx=10, pady=(5, 10), fill="x")

        ctk.CTkLabel(pool_ctrl_frame, text="New Pool Name:").pack(anchor="w")
        ctk.CTkEntry(pool_ctrl_frame, textvariable=self.pool_name_var, width=200).pack(fill="x", pady=(0, 5))

        self.btn_create_pool = ctk.CTkButton(pool_ctrl_frame, text="Create New Pool", command=self.create_pool,
                                             state="disabled")
        self.btn_create_pool.pack(fill="x")

        self.btn_add_disk = ctk.CTkButton(pool_ctrl_frame, text="Add Selected to Pool", command=self.add_disks_to_pool,
                                          state="disabled", fg_color="#4a6fa5")
        self.btn_add_disk.pack(fill="x", pady=(5, 0))

    def setup_middle_pane(self):
        middle_frame = ctk.CTkFrame(self)
        middle_frame.grid(row=0, column=1, padx=(0, 10), pady=(10, 5), sticky="nsew")

        ctk.CTkLabel(middle_frame, text="2. Topology & Management", font=("Arial", 16, "bold")).pack(pady=10)

        ctk.CTkLabel(middle_frame, text="Target Pool:").pack(anchor="w", padx=10)
        self.pool_dropdown = ctk.CTkOptionMenu(middle_frame, variable=self.selected_pool_var, values=[])
        self.pool_dropdown.pack(padx=10, fill="x")

        btn_frame = ctk.CTkFrame(middle_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=5)

        self.btn_optimize = ctk.CTkButton(btn_frame, text="Optimize Pool", command=self.optimize_target_pool,
                                          state="disabled", width=100)
        self.btn_optimize.pack(side="left", expand=True, fill="x", padx