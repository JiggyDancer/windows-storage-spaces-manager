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
        if self.tw: return

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

        self.btn_resize_vd = ctk.CTkButton(existing_frame, text="Expand Disk to Max", command=self.resize_existing_vd,
                                           state="disabled")
        self.btn_resize_vd.pack(fill="x", pady=(5, 0))

        # MODIFIED: Replace Columns input with Delete button
        self.btn_delete_vd = ctk.CTkButton(existing_frame, text="Delete Virtual Disk", command=self.delete_vd,
                                           state="disabled", fg_color="#d32f2f", hover_color="#b71c1c")
        self.btn_delete_vd.pack(fill="x", pady=(5, 0))
        ToolTip(self.btn_delete_vd, "Permanently deletes the selected virtual disk. ALL DATA WILL BE LOST.")

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
        self.log_box.tag_config("err_color", foreground="#E57373")

        clear_btn = ctk.CTkButton(log_frame, text="Clear Log", command=lambda: self.log_box.delete("1.0", "end"),
                                  width=80)
        clear_btn.pack(anchor="e", padx=10, pady=(0, 10))

    def change_media_type(self, media_type):
        if not self.selected_context_disk_obj: return
        disk_name = self.selected_context_disk_obj.get("FriendlyName", "Unknown")
        disk_uid = self.selected_context_disk_obj.get("UniqueId", "")
        try:
            storage_ops.set_media_type(disk_uid, media_type)
            messagebox.showinfo("Success", f"Media Type for {disk_name} forced to {media_type}.")
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def refresh_data(self):
        def fetch():
            try:
                disks = storage_ops.get_physical_disks()
                pools = storage_ops.get_storage_pools()
                topology = storage_ops.get_pool_topology()
                self.after(0, lambda: self._update_ui(disks, pools, topology))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Refresh Error", str(e)))

        threading.Thread(target=fetch, daemon=True).start()

    def _update_ui(self, disks, pools, topology):
        selected_uids = {cb.disk_uid for cb in self.disk_checkboxes if cb.get() == 1}
        current_pool = self.selected_pool_var.get()

        # Refresh Left Pane
        for widget in self.disk_container.winfo_children(): widget.destroy()
        self.disk_checkboxes.clear()

        for i, disk in enumerate(disks):
            bg_color = "#2b2b2b" if i % 2 == 0 else "transparent"
            row_frame = ctk.CTkFrame(self.disk_container, fg_color=bg_color, corner_radius=0)
            row_frame.pack(fill="x", pady=1)

            name = disk.get("FriendlyName", "Unknown")
            can_pool = disk.get("CanPool", False)

            cb = ctk.CTkCheckBox(row_frame, text="", width=self.table_layout[0][1], command=self.validate_state)
            cb.disk_obj = disk
            cb.disk_uid = disk.get("UniqueId", "")
            if not can_pool: cb.configure(state="disabled")
            cb.pack(side="left")
            self.disk_checkboxes.append(cb)

            data = [
                str(disk.get("Number", "?")),
                name[:20],
                disk.get("MediaType", "Unk")[:4],
                f"{disk.get('SizeGB', 0):.2f}",
                disk.get("Usage", "Unk")[:8],
                disk.get("OperationalStatus", "Unk")[:8],
                str(can_pool)
            ]

            for idx, val in enumerate(data):
                w = self.table_layout[idx + 1][1]
                anchor = "e" if idx == 3 else "w"
                lbl = ctk.CTkLabel(row_frame, text=val, width=w, anchor=anchor, font=self.table_font)
                lbl.pack(side="left", padx=2)

            row_frame.bind("<Button-3>", lambda e, d=disk: self.show_disk_context_menu(e, d))
            for child in row_frame.winfo_children(): child.bind("<Button-3>",
                                                                lambda e, d=disk: self.show_disk_context_menu(e, d))

        # Refresh Middle Pane (Topology)
        for widget in self.topo_container.winfo_children(): widget.destroy()
        if not topology:
            ctk.CTkLabel(self.topo_container, text="No Storage Pools Found.", text_color="gray").pack(anchor="w",
                                                                                                      padx=10)

        for pool_name, data in topology.items():
            pool_lbl = ctk.CTkLabel(self.topo_container, text=f"🗀 Pool: {pool_name}", font=("Arial", 14, "bold"),
                                    text_color="#3a7ebf")
            pool_lbl.pack(anchor="w", pady=(10, 0), padx=5)

            if data["disks"]:
                ctk.CTkLabel(self.topo_container, text="  ├── Physical Disks:", font=("Arial", 11, "bold")).pack(
                    anchor="w", padx=15)
                for d in data["disks"]:
                    d_info = f"  │   • {d.get('FriendlyName')} ({d.get('SizeGB')}GB, {d.get('MediaType')})"
                    ctk.CTkLabel(self.topo_container, text=d_info).pack(anchor="w", padx=20)

            if data.get("vdisks"):
                ctk.CTkLabel(self.topo_container, text="  └── Virtual Disks:", font=("Arial", 11, "bold")).pack(
                    anchor="w", padx=15)
                for vd in data["vdisks"]:
                    vd_info = (f"      ◦ {vd.get('FriendlyName')} | {vd.get('ResiliencySettingName')} | "
                               f"Cols: {vd.get('NumberOfColumns')} | {vd.get('SizeGB')}GB")
                    ctk.CTkLabel(self.topo_container, text=vd_info).pack(anchor="w", padx=20)

        # Refresh Dropdowns
        self.pool_list = [p.get("FriendlyName") for p in pools if p.get("FriendlyName")]
        if self.pool_list:
            self.pool_dropdown.configure(values=self.pool_list)
            if current_pool not in self.pool_list: self.selected_pool_var.set(self.pool_list[0])
        else:
            self.pool_dropdown.configure(values=["No Pools Found"])
            self.selected_pool_var.set("No Pools Found")

        for cb in self.disk_checkboxes:
            if cb.disk_uid in selected_uids: cb.select()

        self.validate_state()

    def on_pool_change(self, *args):
        pool = self.selected_pool_var.get()
        if pool and pool != "No Pools Found":
            try:
                vdisks = storage_ops.get_virtual_disks(pool)
                vd_names = [vd.get("FriendlyName") for vd in vdisks if vd.get("FriendlyName")]
                if vd_names:
                    self.vd_dropdown.configure(values=vd_names)
                    self.selected_vd_var.set(vd_names[0])
                else:
                    self.vd_dropdown.configure(values=["No VDisks"])
                    self.selected_vd_var.set("No VDisks")
            except:
                self.vd_dropdown.configure(values=["Error"])
        else:
            self.vd_dropdown.configure(values=["Select Pool First"])
            self.selected_vd_var.set("Select Pool First")
        self.validate_state()

    def show_disk_context_menu(self, event, disk_obj):
        self.selected_context_disk_obj = disk_obj
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def validate_state(self, *args):
        selected_disks = [cb.disk_obj for cb in self.disk_checkboxes if cb.get() == 1]
        pool_name = self.pool_name_var.get().strip()
        current_pool = self.selected_pool_var.get()
        has_valid_pool = current_pool != "" and current_pool != "No Pools Found"
        vd_name = self.vd_name_var.get().strip()

        if len(selected_disks) > 0 and len(pool_name) > 0:
            self.btn_create_pool.configure(state="normal")
        else:
            self.btn_create_pool.configure(state="disabled")

        if has_valid_pool and len(selected_disks) > 0:
            self.btn_add_disk.configure(state="normal")
        else:
            self.btn_add_disk.configure(state="disabled")

        tier_state = "normal" if has_valid_pool else "disabled"
        self.btn_tier_hdd.configure(state=tier_state)
        self.btn_tier_ssd.configure(state=tier_state)
        self.btn_tier_nvme.configure(state=tier_state)
        self.btn_optimize.configure(state=tier_state)

        if has_valid_pool and len(vd_name) > 0:
            self.btn_create_vd.configure(state="normal")
        else:
            self.btn_create_vd.configure(state="disabled")

        current_vd = self.selected_vd_var.get()
        can_modify_vd = has_valid_pool and current_vd and current_vd not in ["No VDisks", "Select Pool First", "Error"]

        if can_modify_vd:
            self.btn_resize_vd.configure(state="normal")
        else:
            self.btn_resize_vd.configure(state="disabled")

        # Update Delete button state
        if can_modify_vd:
            self.btn_delete_vd.configure(state="normal")
        else:
            self.btn_delete_vd.configure(state="disabled")

    def create_pool(self):
        if not messagebox.askyesno("Confirm", "Create new pool?"): return
        try:
            storage_ops.create_pool(self.pool_name_var.get(),
                                    [cb.disk_obj for cb in self.disk_checkboxes if cb.get() == 1])
            messagebox.showinfo("Success", "Pool Created.")
            self.pool_name_var.set("")
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def add_disks_to_pool(self):
        pool = self.selected_pool_var.get()
        disks = [cb.disk_obj for cb in self.disk_checkboxes if cb.get() == 1]
        if not messagebox.askyesno("Confirm", f"Add {len(disks)} disks to '{pool}'?"): return
        try:
            storage_ops.add_disks_to_pool(pool, disks)
            messagebox.showinfo("Success", "Disks added.")
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def optimize_target_pool(self):
        pool = self.selected_pool_var.get()
        threading.Thread(target=lambda: storage_ops.optimize_pool(pool)).start()
        messagebox.showinfo("Started", "Optimization started.")

    def create_tier(self, label, media_type):
        pool = self.selected_pool_var.get()
        try:
            storage_ops.create_tier(pool, f"{pool}_{label}", media_type)
            messagebox.showinfo("Success", "Tier created.")
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def create_vd(self):
        pool = self.selected_pool_var.get()
        vd_name = self.vd_name_var.get()
        res = self.vd_resiliency.get()
        cols = self.vd_columns.get().strip()
        intl = self.vd_interleave.get().strip()
        size = self.vd_size.get().strip()
        try:
            storage_ops.create_virtual_disk(pool, vd_name, res, cols, intl, size)
            messagebox.showinfo("Success", "Virtual Disk Created.")
            self.vd_name_var.set("")
            self.on_pool_change()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def resize_existing_vd(self):
        pool = self.selected_pool_var.get()
        vd_name = self.selected_vd_var.get()
        if not messagebox.askyesno("Confirm", f"Expand '{vd_name}' to maximum?"): return
        try:
            storage_ops.resize_virtual_disk(pool, vd_name, "maximum")
            messagebox.showinfo("Success", "Disk expanded.")
            self.on_pool_change()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # NEW: Delete Virtual Disk Logic
    def delete_vd(self):
        pool = self.selected_pool_var.get()
        vd_name = self.selected_vd_var.get()

        warning_msg = (f"Are you sure you want to delete the virtual disk '{vd_name}'?\n\n"
                       "** WARNING: ALL DATA ON THIS DISK WILL BE PERMANENTLY LOST. **\n\n"
                       "This action cannot be undone.")

        if not messagebox.askyesno("!!! DELETE WARNING !!!", warning_msg):
            return

        try:
            storage_ops.remove_virtual_disk(pool, vd_name)
            messagebox.showinfo("Success", f"Virtual Disk '{vd_name}' deleted.")
            self.on_pool_change()  # Refresh list
            self.refresh_data()
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
        exe = sys.executable
        if exe.lower().endswith("python.exe"): exe = exe[:-10] + "pythonw.exe"
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, os.path.dirname(os.path.abspath(sys.argv[0])),
                                            1)