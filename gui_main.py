import sys
import os
import ctypes
import subprocess
import tkinter as tk
from tkinter import messagebox, Menu
import threading

try:
    import customtkinter as ctk
except ImportError:
    temp_root = tk.Tk()
    temp_root.withdraw()
    messagebox.showinfo("Initial Setup", "Missing dependency 'customtkinter'. Installing now...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "customtkinter"])
        import customtkinter as ctk
    except Exception as e:
        messagebox.showerror("Installation Error", f"Failed to automatically install customtkinter.\n\n{e}")
        sys.exit(1)
    finally:
        temp_root.destroy()

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
        if self.tw: return  # Prevent flicker

        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 25
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tw, text=self.text, justify='left',
                         background="#2b2b2b", foreground="white",
                         relief='solid', borderwidth=1,
                         font=("Arial", 10), padx=8, pady=5)
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
        self.new_columns_var = ctk.StringVar()

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

        # FIX: Strict widths with fixed font to ensure alignment
        self.table_font = ("Consolas", 11)
        self.table_layout = [
            ("", 30),  # Checkbox
            ("Num", 40),
            ("Name", 180),
            ("Media", 70),
            ("Size (GB)", 80),
            ("Usage", 80),
            ("Status", 70),
            ("Can Pool", 60)
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

        # Pool Controls
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
        self.btn_optimize.pack(side="left", expand=True, fill="x", padx=(0, 5))

        tier_frame = ctk.CTkFrame(middle_frame)
        tier_frame.pack(padx=10, pady=5, fill="x")
        ctk.CTkLabel(tier_frame, text="Storage Tiers", font=("Arial", 12, "bold")).pack(pady=5)

        self.btn_tier_hdd = ctk.CTkButton(tier_frame, text="Create HDD Tier",
                                          command=lambda: self.create_tier("HDD", "HDD"), state="disabled")
        self.btn_tier_hdd.pack(pady=2, padx=10, fill="x")
        self.btn_tier_ssd = ctk.CTkButton(tier_frame, text="Create SSD Tier",
                                          command=lambda: self.create_tier("SSD", "SSD"), state="disabled")
        self.btn_tier_ssd.pack(pady=2, padx=10, fill="x")
        self.btn_tier_nvme = ctk.CTkButton(tier_frame, text="Create NVMe Tier",
                                           command=lambda: self.create_tier("NVMe", "SCM"), state="disabled")
        self.btn_tier_nvme.pack(pady=2, padx=10, fill="x")

        self.topo_container = ctk.CTkScrollableFrame(middle_frame, label_text="Pool Topology", fg_color="#212121")
        self.topo_container.pack(padx=10, pady=(15, 10), fill="both", expand=True)

    def setup_right_pane(self):
        right_frame = ctk.CTkFrame(self)
        right_frame.grid(row=0, column=2, padx=(0, 10), pady=(10, 5), sticky="nsew")

        ctk.CTkLabel(right_frame, text="3. Virtual Disk Manager", font=("Arial", 16, "bold")).pack(pady=10)

        # Existing Virtual Disk Section
        existing_frame = ctk.CTkFrame(right_frame)
        existing_frame.pack(padx=10, pady=5, fill="x")

        ctk.CTkLabel(existing_frame, text="Existing Virtual Disk:").pack(anchor="w", pady=(10, 0))
        self.vd_dropdown = ctk.CTkOptionMenu(existing_frame, variable=self.selected_vd_var,
                                             values=["No Pools Selected"])
        self.vd_dropdown.pack(fill="x", pady=(0, 5))

        # Resize
        self.btn_resize_vd = ctk.CTkButton(existing_frame, text="Expand Disk to Max", command=self.resize_existing_vd,
                                           state="disabled")
        self.btn_resize_vd.pack(fill="x", pady=(5, 0))

        # FIX: Change Columns Section
        mod_frame = ctk.CTkFrame(existing_frame, fg_color="transparent")
        mod_frame.pack(fill="x", pady=5)

        self.vd_col_entry = ctk.CTkEntry(mod_frame, placeholder_text="New Column Count", width=150)
        self.vd_col_entry.pack(side="left", padx=(0, 5), fill="x", expand=True)

        self.btn_set_col = ctk.CTkButton(mod_frame, text="Set Columns", command=self.set_columns, state="disabled",
                                         width=80)
        self.btn_set_col.pack(side="left")
        ToolTip(self.btn_set_col,
                "WARNING: Changing columns repairs/resyncs the volume. Data remains but operation is intensive.")

        # Separator
        ctk.CTkLabel(right_frame, text="―――――――――――――――――――", text_color="gray").pack(pady=10)

        # New Virtual Disk Section
        new_frame = ctk.CTkFrame(right_frame)
        new_frame.pack(padx=10, pady=5, fill="both", expand=True)

        ctk.CTkLabel(new_frame, text="Create New Virtual Disk", font=("Arial", 12, "bold")).pack(anchor="w")

        ctk.CTkLabel(new_frame, text="New Disk Name:").pack(anchor="w", padx=5, pady=(10, 0))
        self.vd_name_entry = ctk.CTkEntry(new_frame, textvariable=self.vd_name_var)
        self.vd_name_entry.pack(fill="x", padx=5, pady=(0, 5))

        ctk.CTkLabel(new_frame, text="Resiliency Setting:").pack(anchor="w", padx=5, pady=(10, 0))
        self.vd_resiliency = ctk.CTkOptionMenu(new_frame,
                                               values=["Simple", "Two-Way Mirror", "Three-Way Mirror", "Single Parity",
                                                       "Dual Parity"])
        self.vd_resiliency.pack(fill="x", padx=5, pady=(0, 5))

        ctk.CTkLabel(new_frame, text="Number of Columns (Blank = Auto):").pack(anchor="w", padx=5, pady=(10, 0))
        self.vd_columns = ctk.CTkEntry(new_frame, placeholder_text="Auto")
        self.vd_columns.pack(fill="x", padx=5, pady=(0, 5))

        ctk.CTkLabel(new_frame, text="Interleave Size KB (Blank = Auto):").pack(anchor="w", padx=5, pady=(10, 0))
        self.vd_interleave = ctk.CTkEntry(new_frame, placeholder_text="Auto")
        self.vd_interleave.pack(fill="x", padx=5, pady=(0, 5))

        ctk.CTkLabel(new_frame, text="Size in GB (Blank = Max):").pack(anchor="w", padx=5, pady=(10, 0))
        self.vd_size = ctk.CTkEntry(new_frame, placeholder_text="Maximum")
        self.vd_size.pack(fill="x", padx=5, pady=(0, 20))

        self.btn_create_vd = ctk.CTkButton(new_frame, text="Create Virtual Disk", command=self.create_vd,
                                           state="disabled")
        self.btn_create_vd.pack(pady=10)

    def setup_bottom_pane(self):
        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=1, column=0, columnspan=3, padx=10, pady=(5, 10), sticky="nsew")

        ctk.CTkLabel(log_frame, text="PowerShell Activity Log", font=("Arial", 12, "bold")).pack(anchor="w", padx=10,
                                                                                                 pady=5)

        self.log_box = ctk.CTkTextbox(log_frame, font=("Consolas", 11), wrap="word")
        self.log_box.pack(padx=10, pady=(0, 10), fill="both", expand=True)
        self.log_box.configure(state="disabled")

        self.log_box.tag_config("cmd_color", foreground="#4DB6AC")
        self.log_box.tag_config("out_color", foreground="#B0BEC5")
        self.log_box.tag_config