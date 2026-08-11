import sys
import os
import ctypes
import subprocess
import tkinter as tk
from tkinter import messagebox, Menu

# Auto-install dependency if missing
try:
    import customtkinter as ctk
except ImportError:
    temp_root = tk.Tk()
    temp_root.withdraw()
    messagebox.showinfo("Initial Setup", "Missing dependency 'customtkinter'. Installing now, please wait a moment...")
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
        self.selected_context_disk = None
        
        self.setup_left_pane()
        self.setup_middle_pane()
        self.setup_right_pane()
        self.setup_bottom_pane()
        
        backend.log_callback = self.write_log
        self.refresh_data()

    def write_log(self, message):
        self.log_box.configure(state="normal")
        
        # Route the message to the appropriate color tag based on its prefix
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
        ToolTip(btn_refresh, "Executes Get-PhysicalDisk and Get-StoragePool to rebuild the current hardware state.\nUseful if drives were recently hot-plugged or removed.")

        ctk.CTkLabel(left_frame, text="All Physical Disks (Right-click for options)").pack(anchor="w", padx=10, pady=(5, 0))
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
        self.context_menu.add_command(label="Force MediaType: SCM (NVMe)", command=lambda: self.change_media_type("SCM"))
        self.context_menu.add_command(label="Force MediaType: SSD", command=lambda: self.change_media_type("SSD"))
        self.context_menu.add_command(label="Force MediaType: HDD", command=lambda: self.change_media_type("HDD"))

        pool_ctrl_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        pool_ctrl_frame.pack(padx=10, pady=(5, 10), fill="x")
        
        ctk.CTkLabel(pool_ctrl_frame, text="New Pool Name:").pack(side="left", padx=(0, 10))
        ctk.CTkEntry(pool_ctrl_frame, textvariable=self.pool_name_var, width=200).pack(side="left", padx=(0, 10))
        self.btn_create_pool = ctk.CTkButton(pool_ctrl_frame, text="Create Pool", command=self.create_pool, state="disabled")
        self.btn_create_pool.pack(side="left")
        ToolTip(self.btn_create_pool, "Groups the selected raw physical disks into a unified logical pool.\nAvoid special characters in the pool name to prevent mounting errors.")

    def setup_middle_pane(self):
        middle_frame = ctk.CTkFrame(self)
        middle_frame.grid(row=0, column=1, padx=(0, 10), pady=(10, 5), sticky="nsew")

        ctk.CTkLabel(middle_frame, text="2. Topology & Tiers", font=("Arial", 16, "bold")).pack(pady=10)

        ctk.CTkLabel(middle_frame, text="Target Pool:").pack(anchor="w", padx=10)
        
        pool_action_frame = ctk.CTkFrame(middle_frame, fg_color="transparent")
        pool_action_frame.pack(fill="x", padx=10, pady=(0, 15))
        
        self.pool_dropdown = ctk.CTkOptionMenu(pool_action_frame, variable=self.selected_pool_var, values=[])
        self.pool_dropdown.pack(side="left", fill="x", expand=True)
        
        self.btn_optimize = ctk.CTkButton(pool_action_frame, text="Optimize", width=80, command=self.optimize_target_pool, state="disabled")
        self.btn_optimize.pack(side="left", padx=(10, 0))
        ToolTip(self.btn_optimize, "Executes Optimize-StoragePool as a background job.\nThis command rebalances data slabs across all physical disks evenly.\nHighly recommended after adding a new drive or changing tier configurations.")

        tier_frame = ctk.CTkFrame(middle_frame)
        tier_frame.pack(padx=10, pady=5, fill="x")
        ctk.CTkLabel(tier_frame, text="Storage Tiers", font=("Arial", 12, "bold")).pack(pady=5)
        
        self.btn_tier_hdd = ctk.CTkButton(tier_frame, text="Create HDD Tier", command=lambda: self.create_tier("HDD", "HDD"), state="disabled")
        self.btn_tier_hdd.pack(pady=5, padx=10, fill="x")
        ToolTip(self.btn_tier_hdd, "Defines a Capacity Tier.\nWindows Storage Spaces will automatically allocate 256MB data slabs to mechanical drives.\nUsed by the Heat Map to store 'cold' infrequently accessed data.")
        
        self.btn_tier_ssd = ctk.CTkButton(tier_frame, text="Create SSD Tier", command=lambda: self.create_tier("SSD", "SSD"), state="disabled")
        self.btn_tier_ssd.pack(pady=5, padx=10, fill="x")
        ToolTip(self.btn_tier_ssd, "Defines a Standard Performance Tier.\nStorage Spaces will automatically move 'warm' data blocks to SATA/SAS SSDs for faster access.")
        
        self.btn_tier_nvme = ctk.CTkButton(tier_frame, text="Create NVMe Tier", command=lambda: self.create_tier("NVMe", "SCM"), state="disabled")
        self.btn_tier_nvme.pack(pady=5, padx=10, fill="x")
        ToolTip(self.btn_tier_nvme, "Defines an Ultra-Performance Tier.\nRelies on Storage Class Memory (SCM) or manually forced NVMe drives.\nUsed for caching and handling 'hot' data blocks with high IOPS requirements.")

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
        ToolTip(self.vd_name_entry, "This text establishes the namespace and acts as the volume label shown within Windows Explorer upon formatting.")

        ctk.CTkLabel(vd_frame, text="Resiliency Setting:").pack(anchor="w", padx=10, pady=(10, 0))
        resiliency_opts = ["Simple", "Two-Way Mirror", "Three-Way Mirror", "Single Parity", "Dual Parity"]
        self.vd_resiliency = ctk.CTkOptionMenu(vd_frame, values=resiliency_opts)
        self.vd_resiliency.pack(padx=10, pady=(0, 5), fill="x")
        ToolTip(self.vd_resiliency, 
                "Simple (Striping):\n"
                "• Capacity: 100% usable.\n"
                "• Read/Write: Extremely high. Data chunks are simultaneously distributed across all active disks.\n"
                "• Fault Tolerance: None. The loss of a single drive completely destroys the virtual disk.\n\n"
                "Two-Way Mirror:\n"
                "• Capacity: 50% usable.\n"
                "• Read: High. Reads are dynamically parallelized across the mirrored pairs.\n"
                "• Write: Moderate. Write operations must commit data to both drives, limited by the slower disk.\n"
                "• Fault Tolerance: Survives 1 drive failure. Requires a minimum of 2 physical disks.\n\n"
                "Three-Way Mirror:\n"
                "• Capacity: 33.3% usable.\n"
                "• Read: High.\n"
                "• Write: Moderate-Low. Write operations must successfully commit to three separate physical drives.\n"
                "• Fault Tolerance: Survives any 2 simultaneous drive failures. Requires a minimum of 5 physical disks.\n\n"
                "Single Parity:\n"
                "• Capacity: ~(N-1)/N usable (e.g., yielding 66% on a 3-drive array).\n"
                "• Read: High. Effectively scales like a striped array.\n"
                "• Write: Low. Parity calculation overhead and journal disk bottlenecks severely throttle sequential write speeds.\n"
                "• Fault Tolerance: Survives 1 drive failure. Requires a minimum of 3 physical disks.\n\n"
                "Dual Parity:\n"
                "• Capacity: ~(N-2)/N usable (e.g., yielding 71% on a 7-drive array).\n"
                "• Read: High.\n"
                "• Write: Very Low. Double parity calculation generates substantial computational and I/O overhead.\n"
                "• Fault Tolerance: Survives 2 drive failures. Requires a minimum of 7 physical disks.")

        ctk.CTkLabel(vd_frame, text="Number of Columns (Blank = Auto):").pack(anchor="w", padx=10, pady=(10, 0))
        self.vd_columns = ctk.CTkEntry(vd_frame, placeholder_text="Auto")
        self.vd_columns.pack(padx=10, pady=(0, 5), fill="x")
        ToolTip(self.vd_columns, "Dictates the number of underlying physical disks across which a single data stripe is split.\nMore columns universally yields better sequential read/write throughput.\nWarning: You can only expand the pool later by adding disks in multiples of your column count.")

        ctk.CTkLabel(vd_frame, text="Interleave Size KB (Blank = Auto):").pack(anchor="w", padx=10, pady=(10, 0))
        self.vd_interleave = ctk.CTkEntry(vd_frame, placeholder_text="256")
        self.vd_interleave.pack(padx=10, pady=(0, 5), fill="x")
        ToolTip(self.vd_interleave, "Defines the exact block size of a data stripe written to a single column.\n• 256KB is the default Windows standard.\n• Use 64KB if optimizing for heavy SQL Database usage.\n• Use 256KB or higher for large contiguous files (e.g., high-resolution video rendering/editing).")

        ctk.CTkLabel(vd_frame, text="Size in GB (Blank = Max):").pack(anchor="w", padx=10, pady=(10, 0))
        self.vd_size = ctk.CTkEntry(vd_frame, placeholder_text="Maximum")
        self.vd_size.pack(padx=10, pady=(0, 20), fill="x")
        ToolTip(self.vd_size, "The target allocated capacity of the Virtual Disk in Gigabytes.\nLeave this field entirely blank to prompt Storage Spaces to consume all available capacity within the selected pool.")

        self.btn_create_vd = ctk.CTkButton(vd_frame, text="Create Virtual Disk", command=self.create_vd, state="disabled")
        self.btn_create_vd.pack(pady=10)

    def setup_bottom_pane(self):
        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=1, column=0, columnspan=3, padx=10, pady=(5, 10), sticky="nsew")
        
        ctk.CTkLabel(log_frame, text="PowerShell Activity Log", font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=5)
        
        self.log_box = ctk.CTkTextbox(log_frame, font=("Consolas", 11), wrap="word")
        self.log_box.pack(padx=10, pady=(0, 10), fill="both", expand=True)
        self.log_box.configure(state="disabled")

        # Configure color tags for log output formatting
        self.log_box.tag_config("cmd_color", foreground="#4DB6AC")  # Teal/Green
        self.log_box.tag_config("out_color", foreground="#B0BEC5")  # Light Gray/Blue
        self.log_box.tag_config("err_color", foreground="#E57373")  # Red

    def show_disk_context_menu(self, event, disk_name):
        self.selected_context_disk = disk_name
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def change_media_type(self, media_type):
        if not self.selected_context_disk: 
            return
        try:
            storage_ops.set_media_type(self.selected_context_disk, media_type)
            messagebox.showinfo("Success", f"Media Type for {self.selected_context_disk} forced to {media_type}.")
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def refresh_data(self):
        for widget in self.disk_container.winfo_children():
            widget.destroy()
        self.disk_checkboxes.clear()

        try:
            disks = storage_ops.get_physical_disks()
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
                cb.disk_name = name
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

                row_frame.bind("<Button-3>", lambda e, d_name=name: self.show_disk_context_menu(e, d_name))
                for child in row_frame.winfo_children():
                    child.bind("<Button-3>", lambda e, d_name=name: self.show_disk_context_menu(e, d_name))

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load physical disks: {e}")

        for widget in self.topo_container.winfo_children():
            widget.destroy()

        try:
            topology = storage_ops.get_pool_topology()
            if not topology:
                ctk.CTkLabel(self.topo_container, text="No Storage Pools Found.", text_color="gray").pack(anchor="w", padx=10, pady=10)

            for pool_name, data in topology.items():
                pool_lbl = ctk.CTkLabel(self.topo_container, text=f"🖴 Pool: {pool_name}", font=("Arial", 14, "bold"), text_color="#3a7ebf")
                pool_lbl.pack(anchor="w", pady=(10, 0), padx=5)
                
                if data["tiers"]:
                    ctk.CTkLabel(self.topo_container, text="  ↳ Tiers:", font=("Arial", 12, "bold")).pack(anchor="w", padx=15)
                    for tier in data["tiers"]:
                        t_name = tier.get("FriendlyName", "Unknown")
                        t_media = tier.get("MediaType", "Unknown")
                        t_size = tier.get("SizeGB", 0)
                        ctk.CTkLabel(self.topo_container, text=f"      • {t_name} [{t_media}] ({t_size} GB)").pack(anchor="w", padx=20)
                
                if data["disks"]:
                    ctk.CTkLabel(self.topo_container, text="  ↳ Assigned Physical Disks:", font=("Arial", 12, "bold")).pack(anchor="w", padx=15)
                    for disk in data["disks"]:
                        d_name = disk.get("FriendlyName", "Unknown")
                        d_media = disk.get("MediaType", "Unknown")
                        d_usage = disk.get("Usage", "Unknown")
                        d_size = disk.get("SizeGB", 0)
                        ctk.CTkLabel(self.topo_container, text=f"      • {d_name} | {d_media} | {d_size} GB | {d_usage}").pack(anchor="w", padx=20)
        except Exception as e:
            pass

        try:
            pools = storage_ops.get_storage_pools()
            self.pool_list = [p.get("FriendlyName") for p in pools if p.get("FriendlyName")]
            if self.pool_list:
                self.pool_dropdown.configure(values=self.pool_list)
                if self.selected_pool_var.get() not in self.pool_list:
                    self.selected_pool_var.set(self.pool_list[0])
            else:
                self.pool_dropdown.configure(values=["No Pools Found"])
                self.selected_pool_var.set("No Pools Found")
        except Exception as e:
            pass
            
        self.validate_state()

    def validate_state(self, *args):
        checked_disks = [cb.disk_name for cb in self.disk_checkboxes if cb.get() == 1]
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

    def create_pool(self):
        pool_name = self.pool_name_var.get().strip()
        selected_disks = [cb.disk_name for cb in self.disk_checkboxes if cb.get() == 1]
        try:
            storage_ops.create_pool(pool_name, selected_disks)
            messagebox.showinfo("Success", f"Pool '{pool_name}' created.")
            self.pool_name_var.set("")
            self.refresh_data()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def optimize_target_pool(self):
        pool = self.selected_pool_var.get()
        try:
            storage_ops.optimize_pool(pool)
            messagebox.showinfo("Optimization Started", f"Background optimization job initiated for pool '{pool}'.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

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
        cols = self.vd_columns.get()
        intl = self.vd_interleave.get()
        sz = self.vd_size.get()

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
        if exe.lower().endswith("python.exe"):
            exe = exe[:-10] + "pythonw.exe"
            
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, working_dir, 1)
        sys.exit()