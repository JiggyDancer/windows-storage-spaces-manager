import sys
import os
import ctypes
import subprocess
import tkinter as tk
from tkinter import messagebox, Menu
import threading

# When using 'uv', dependencies must be installed via 'uv add' or 'uv sync'.
# We remove the runtime pip installer to prevent conflicts with uv's managed environment.
try:
    import customtkinter as ctk
except ImportError:
    # If running via uv, the user likely forgot to sync dependencies.
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Dependency Missing",
        "The 'customtkinter' package is not found.\n\n"
        "If using uv, please run:\n    uv add customtkinter\n"
        "Then try running the application again."
    )
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
        if not self.text:
            return

        # If the tooltip already exists, don't create it again
        if self.tw:
            return

        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25

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
        self.geometry("1600x900")

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
        self.selected_pool_var.trace_add("write", self.validate_state)

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
        self.update_idletasks()

    def setup_left_pane(self):
        left_frame = ctk.CTkFrame(self)
        left_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")

        ctk.CTkLabel(left_frame, text="1. Physical Disks & Pool Creation", font=("Arial", 16, "bold")).pack(pady=10)

        btn_refresh = ctk.CTkButton(left_frame, text="Refresh Hardware", command=self.refresh_data)
        btn_refresh.pack(pady=5)
        ToolTip(btn_refresh, "Executes Get-PhysicalDisk and Get-StoragePool to rebuild the current hardware state.")

        ctk.CTkLabel(left_frame, text="All Physical Disks (Right-click for options)").pack(anchor="w", padx=10,
                                                                                           pady=(5, 0))
        header_frame = ctk.CTkFrame(left_frame, fg_color="#343638", corner_radius=0)
        header_frame.pack(padx=10, pady=(5, 0), fill="x")

        self.table_layout = [
            ("", 30, "center", False),
            ("Num", 40, "center", False),
            ("Name", 200, "w", True),
            ("Media", 80, "center", False),
            ("Size (GB)", 80, "e", False),
            ("Usage", 90, "w", False),
            ("Status", 70, "w", False),
            ("Can Pool", 60, "center", False)
        ]

        for text, width, anchor, expand in self.table_layout:
            lbl = ctk.CTkLabel(header_frame, text=text, width=width, anchor=anchor, font=("Arial", 12, "bold"))
            lbl.pack(side="left", padx=5, fill="x" if expand else "none", expand=expand)

        self.disk_container = ctk.CTkScrollableFrame(left_frame, fg_color="#212121", corner_radius=0)
        self.disk_container.pack(padx=10, pady=(0, 10), fill="both", expand=True)

        self.context_menu = Menu(self, tearoff=0, bg="#2b2b2b", fg="white", activebackground="#1f538d")
        self.context_menu.add_command(label="Force MediaType: SCM (NVMe)",
                                      command=lambda: self.change_media_type("SCM"))
        self.context_menu.add_command(label="Force MediaType: SSD", command=lambda: self.change_media_type("SSD"))
        self.context_menu.add_command(label="Force MediaType: HDD", command=lambda: self.change_media_type("HDD"))

        pool_ctrl_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        pool_ctrl_frame.pack(padx=10, pady=(5, 10), fill="x")

        ctk.CTkLabel(pool_ctrl_frame, text="New Pool Name:").pack(side="left", padx=(0, 10))
        ctk.CTkEntry(pool_ctrl_frame, textvariable=self.pool_name_var, width=200).pack(side="left", padx=(0, 10))
        self.btn_create_pool = ctk.CTkButton(pool_ctrl_frame, text="Create Pool", command=self.create_pool,
                                             state="disabled")
        self.btn_create_pool.pack(side="left")
        ToolTip(self.btn_create_pool, "Groups the selected raw physical disks into a unified logical pool.")

    def setup_middle_pane(self):
        middle_frame = ctk.CTkFrame(self)
        middle_frame.grid(row=0, column=1, padx=(0, 10), pady=(10, 5), sticky="nsew")

        ctk.CTkLabel(middle_frame, text="2. Topology & Tiers", font=("Arial", 16, "bold")).pack(pady=10)
        ctk.CTkLabel(middle_frame, text="Target Pool:").pack(anchor="w", padx=10)

        pool_action_frame = ctk.CTkFrame(middle_frame, fg_color="transparent")
        pool_action_frame.pack(fill="x", padx=10, pady=(0, 15))

        self.pool_dropdown = ctk.CTkOptionMenu(pool_action_frame, variable=self.selected_pool_var, values=[])
        self.pool_dropdown.pack(side="left", fill="x", expand=True)

        self.btn_optimize = ctk.CTkButton(pool_action_frame, text="Optimize", width=80,
                                          command=self.optimize_target_pool, state="disabled")
        self.btn_optimize.pack(side="left", padx=(10, 0))
        ToolTip(self.btn_optimize, "Executes Optimize-StoragePool to rebalance data across disks.")

        tier_frame = ctk.CTkFrame(middle_frame)
        tier_frame.pack(padx=10, pady=5, fill="x")
        ctk.CTkLabel(tier_frame, text="Storage Tiers", font=("Arial", 12, "bold")).pack(pady=5)

        self.btn_tier_hdd = ctk.CTkButton(tier_frame, text="Create HDD Tier",
                                          command=lambda: self.create_tier("HDD", "HDD"), state="disabled")
        self.btn_tier_hdd.pack(pady=5, padx=10, fill="x")

        self.btn_tier_ssd = ctk.CTkButton(tier_frame, text="Create SSD Tier",
                                          command=lambda: self.create_tier("SSD", "SSD"), state="disabled")
        self.btn_tier_ssd.pack(pady=5, padx=10, fill="x")

        self.btn_tier_nvme = ctk.CTkButton(tier_frame, text="Create NVMe Tier",
                                           command=lambda: self.create_tier("NVMe", "SCM"), state="disabled")
        self.btn_tier_nvme.pack(pady=5, padx=10, fill="x")

        self.topo_container = ctk.CTkScrollableFrame(middle_frame, label_text="Storage Topology", fg_color="#212121")
        self.topo_container.pack(padx=10, pady=(15, 10), fill="both", expand=True)

    def setup_right_pane(self):
        right_frame = ctk.CTkFrame(self)
        right_frame.grid(row=0, column=2, padx=(0, 10), pady=(10, 5), sticky="nsew")

        ctk.CTkLabel(right_frame, text="3. Virtual Disk Config", font=("Arial", 16, "bold")).pack(pady=10)

        vd_frame = ctk.CTkFrame(right_frame)
        vd_frame.pack(padx=10, pady=5, fill="both", expand=True)

        ctk.CTkLabel(vd_frame, text="Virtual Disk Name:").pack(anchor="w", padx=10, pady=(10, 0))
        self.vd_name_entry = ctk.CTkEntry(vd_frame, textvariable=self.vd_name_var)
        self.vd_name_entry.pack(padx=10, pady=(0, 5), fill="x")

        ctk.CTkLabel(vd_frame, text="Resiliency Setting:").pack(anchor="w", padx=10, pady=(10, 0))
        resiliency_opts = ["Simple", "Two-Way Mirror", "Three-Way Mirror", "Single Parity", "Dual Parity"]
        self.vd_resiliency = ctk.CTkOptionMenu(vd_frame, values=resiliency_opts)
        self.vd_resiliency.pack(padx=10, pady=(0, 5), fill="x")

        ctk.CTkLabel(vd_frame, text="Number of Columns (Blank = Auto):").pack(anchor="w", padx=10, pady=(10, 0))
        self.vd_columns = ctk.CTkEntry(vd_frame, placeholder_text="Auto")
        self.vd_columns.pack(padx=10, pady=(0, 5), fill="x")

        ctk.CTkLabel(vd_frame, text="Interleave Size KB (Blank = Auto):").pack(anchor="w", padx=10, pady=(10, 0))
        self.vd_interleave = ctk.CTkEntry(vd_frame, placeholder_text="256")
        self.vd_interleave.pack(padx=10, pady=(0, 5), fill="x")

        ctk.CTkLabel(vd_frame, text="Size in GB (Blank = Max):").pack(anchor="w", padx=10, pady=(10, 0))
        self.vd_size = ctk.CTkEntry(vd_frame, placeholder_text="Maximum")
        self.vd_size.pack(padx=10, pady=(0, 20), fill="x")

        self.btn_create_vd = ctk.CTkButton(vd_frame, text="Create Virtual Disk", command=self.create_vd,
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
        self.log_box.tag_config("err_color", foreground="#E57373")

        clear_btn = ctk.CTkButton(log_frame, text="Clear Log", command=self.clear_log, width=80)
        clear_btn.pack(anchor="e", padx=10, pady=(0, 10))

    def clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def show_disk_context_menu(self, event, disk_obj):
        self.selected_context_disk_obj = disk_obj
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def change_media_type(self, media_type):
        if not self.selected_context_disk_obj:
            return
        disk_name = self.selected_context_disk_obj.get("FriendlyName", "Unknown")
        disk_uid = self.selected_context_disk_obj.get("UniqueId", "")
        try:
            storage_ops.set_media_type(disk_uid, media_type)
            messagebox.showinfo("Success", f"Media Type for {disk_name} forced to {media_type}.")
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def validate_int_field(self, entry, min_val=1, allow_empty=False, allow_auto=False, field_name=""):
        val = entry.get().strip()
        if not val:
            if allow_empty:
                return None
            else:
                raise ValueError(f"{field_name} cannot be empty.")

        if allow_auto and val.lower() == "auto":
            return "auto"

        try:
            num = int(val)
            if num < min_val:
                raise ValueError(f"{field_name} must be at least {min_val}.")
            return num
        except ValueError:
            raise ValueError(f"{field_name} must be a positive integer or 'Auto'.")

    def refresh_data(self):
        def fetch_thread():
            try:
                disks = storage_ops.get_physical_disks()
                pools = storage_ops.get_storage_pools()
                topology = storage_ops.get_pool_topology()
                self.after(0, lambda: self._update_ui(disks, pools, topology))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Refresh Error", str(e)))

        t = threading.Thread(target=fetch_thread, daemon=True)
        t.start()

    def _update_ui(self, disks, pools, topology):
        selected_uids = {cb.disk_uid for cb in self.disk_checkboxes if cb.get() == 1}

        for widget in self.disk_container.winfo_children():
            widget.destroy()
        self.disk_checkboxes.clear()

        for widget in self.topo_container.winfo_children():
            widget.destroy()

        try:
            disks.sort(key=lambda x: int(x.get("Number")) if str(x.get("Number")).isdigit() else 999)
        except:
            pass

        for i, disk in enumerate(disks):
            bg_color = "#2b2b2b" if i % 2 == 0 else "transparent"
            row_frame = ctk.CTkFrame(self.disk_container, fg_color=bg_color, corner_radius=0)
            row_frame.pack(fill="x", pady=1)

            name = disk.get("FriendlyName", "Unknown")
            can_pool = disk.get("CanPool", False)

            cb = ctk.CTkCheckBox(row_frame, text="", width=self.table_layout[0][1], command=self.validate_state)
            cb.disk_obj = disk
            cb.disk_name = name
            cb.disk_uid = disk.get("UniqueId", "")
            if not can_pool:
                cb.configure(state="disabled")
            cb.pack(side="left", padx=5)
            self.disk_checkboxes.append(cb)

            data_mapping = [
                str(disk.get("Number", "?")),
                name,
                disk.get("MediaType", "Unknown"),
                f"{disk.get('SizeGB', 0):.2f}",
                disk.get("Usage", "Unknown"),
                disk.get("OperationalStatus", "Unknown"),
                str(can_pool)
            ]

            for index in range(1, len(self.table_layout)):
                _, width, anchor, expand = self.table_layout[index]
                lbl = ctk.CTkLabel(row_frame, text=data_mapping[index - 1], width=width, anchor=anchor)
                lbl.pack(side="left", padx=5, fill="x" if expand else "none", expand=expand)

            row_frame.bind("<Button-3>", lambda e, d_obj=disk: self.show_disk_context_menu(e, d_obj))
            for child in row_frame.winfo_children():
                child.bind("<Button-3>", lambda e, d_obj=disk: self.show_disk_context_menu(e, d_obj))

        if not topology:
            ctk.CTkLabel(self.topo_container, text="No Storage Pools Found.", text_color="gray").pack(anchor="w",
                                                                                                      padx=10, pady=10)

        for pool_name, data in topology.items():
            pool_lbl = ctk.CTkLabel(self.topo_container, text=f"🖴 Pool: {pool_name}", font=("Arial", 14, "bold"),
                                    text_color="#3a7ebf")
            pool_lbl.pack(anchor="w", pady=(10, 0), padx=5)

            if data["tiers"]:
                ctk.CTkLabel(self.topo_container, text="  ↳ Tiers:", font=("Arial", 12, "bold")).pack(anchor="w",
                                                                                                      padx=15)
                for tier in data["tiers"]:
                    t_name = tier.get("FriendlyName", "Unknown")
                    t_media = tier.get("MediaType", "Unknown")
                    t_size = tier.get("SizeGB", 0)
                    ctk.CTkLabel(self.topo_container, text=f"      • {t_name} [{t_media}] ({t_size} GB)").pack(
                        anchor="w", padx=20)

            if data["disks"]:
                ctk.CTkLabel(self.topo_container, text="  ↳ Assigned Physical Disks:", font=("Arial", 12, "bold")).pack(
                    anchor="w", padx=15)
                for disk in data["disks"]:
                    d_name = disk.get("FriendlyName", "Unknown")
                    d_media = disk.get("MediaType", "Unknown")
                    d_usage = disk.get("Usage", "Unknown")
                    d_size = disk.get("SizeGB", 0)
                    ctk.CTkLabel(self.topo_container,
                                 text=f"      • {d_name} | {d_media} | {d_size} GB | {d_usage}").pack(anchor="w",
                                                                                                      padx=20)

        self.pool_list = [p.get("FriendlyName") for p in pools if p.get("FriendlyName")]
        if self.pool_list:
            self.pool_dropdown.configure(values=self.pool_list)
            if self.selected_pool_var.get() not in self.pool_list:
                self.selected_pool_var.set(self.pool_list[0])
        else:
            self.pool_dropdown.configure(values=["No Pools Found"])
            self.selected_pool_var.set("No Pools Found")

        for cb in self.disk_checkboxes:
            if cb.disk_uid in selected_uids:
                cb.select()

        self.validate_state()

    def validate_state(self, *args):
        checked_disks = [cb.disk_obj for cb in self.disk_checkboxes if cb.get() == 1]
        if len(checked_disks) > 0 and len(self.pool_name_var.get().strip()) > 0:
            self.btn_create_pool.configure(state="normal")
        else:
            self.btn_create_pool.configure(state="disabled")

        current_pool = self.selected_pool_var.get()
        has_valid_pool = current_pool != "" and current_pool != "No Pools Found"

        tier_state = "normal" if has_valid_pool else "disabled"
        self.btn_tier_hdd.configure(state=tier_state)
        self.btn_tier_ssd.configure(state=tier_state)
        self.btn_tier_nvme.configure(state=tier_state)
        self.btn_optimize.configure(state=tier_state)

        if has_valid_pool and len(self.vd_name_var.get().strip()) > 0:
            self.btn_create_vd.configure(state="normal")
        else:
            self.btn_create_vd.configure(state="disabled")

    def run_async(self, func, *args, **kwargs):
        def worker():
            try:
                func(*args, **kwargs)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.after(0, lambda: self.btn_optimize.configure(state="normal"))
                self.after(0, lambda: self.btn_create_pool.configure(state="normal"))
                self.after(0, lambda: self.btn_create_vd.configure(state="normal"))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        if func.__name__ == "optimize_pool":
            self.btn_optimize.configure(state="disabled")
        elif func.__name__ == "create_pool":
            self.btn_create_pool.configure(state="disabled")
        elif func.__name__ == "create_vd":
            self.btn_create_vd.configure(state="disabled")
        messagebox.showinfo("Started", "Operation running in background...")

    def create_pool(self):
        pool_name = self.pool_name_var.get().strip()
        if len(pool_name) < 1:
            messagebox.showwarning("Input Error", "Please enter a pool name.")
            return

        selected_disks = [cb.disk_obj for cb in self.disk_checkboxes if cb.get() == 1]

        if not selected_disks:
            messagebox.showwarning("No Disks Selected", "Please select at least one disk.")
            return

        if not messagebox.askyesno("Confirm Pool Creation",
                                   f"Are you sure you want to create pool '{pool_name}' with {len(selected_disks)} disks?\n"
                                   "This will erase all existing data on these disks."):
            return

        try:
            storage_ops.create_pool(pool_name, selected_disks)
            messagebox.showinfo("Success", f"Pool '{pool_name}' created.")
            self.pool_name_var.set("")
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def optimize_target_pool(self):
        pool = self.selected_pool_var.get()
        if not pool or pool == "No Pools Found":
            messagebox.showwarning("No Pool Selected", "Please select a pool first.")
            return
        self.run_async(storage_ops.optimize_pool, pool)

    def create_tier(self, tier_label, media_type):
        pool = self.selected_pool_var.get()
        tier_name = f"{pool}_{tier_label}"
        try:
            storage_ops.create_tier(pool, tier_name, media_type)
            messagebox.showinfo("Success", f"{tier_label} tier created for pool '{pool}'.")
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def create_vd(self):
        pool = self.selected_pool_var.get()
        vd_name = self.vd_name_var.get().strip()
        res = self.vd_resiliency.get()

        try:
            cols = self.validate_int_field(self.vd_columns, allow_auto=True, field_name="Number of Columns")
            intl = self.validate_int_field(self.vd_interleave, allow_auto=True, field_name="Interleave Size KB")
            sz = self.validate_int_field(self.vd_size, allow_empty=True, allow_auto=True, field_name="Size in GB")
        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
            return

        try:
            storage_ops.create_virtual_disk(pool, vd_name, res, cols, intl, sz)
            messagebox.showinfo("Success", f"Virtual Disk '{vd_name}' created.")
            self.vd_name_var.set("")
        except Exception as e:
            messagebox.showerror("Error", str(e))


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


if __name__ == "__main__":
    if is_admin():
        app = StorageApp()
        app.mainloop()
    else:
        params = " ".join([f'"{arg}"' for arg in sys.argv])
        working_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        exe = sys.executable

        # uv run can sometimes execute via a shim; trying to replace python.exe with pythonw.exe
        # might break the path resolution. It is safer to just use sys.executable as is for elevation.
        # However, if the user explicitly installed pythonw, we can try the old logic.
        # We will keep it simple for uv compatibility:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, working_dir, 1)
        sys.exit()