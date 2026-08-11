import backend

def get_physical_disks():
    cmd = (
        "Get-PhysicalDisk | Select-Object Number, FriendlyName, SerialNumber, "
        "MediaType, HealthStatus, OperationalStatus, Usage, CanPool, "
        "@{Name='SizeGB';Expression={[math]::Round($_.Size / 1GB, 2)}}"
    )
    result = backend.run_ps(cmd)
    if not result:
        return []
    return [result] if isinstance(result, dict) else result

def get_storage_pools():
    cmd = "Get-StoragePool | Where-Object {$_.IsPrimordial -eq $False} | Select-Object FriendlyName, OperationalStatus"
    try:
        result = backend.run_ps(cmd)
        if not result:
            return []
        return [result] if isinstance(result, dict) else result
    except Exception:
        return []

def get_pool_topology():
    pools = get_storage_pools()
    topology = {}
    
    for p in pools:
        pool_name = p.get("FriendlyName")
        if not pool_name:
            continue
            
        tier_cmd = (f"Get-StorageTier -StoragePoolFriendlyName '{pool_name}' | "
                    f"Select-Object FriendlyName, MediaType, "
                    f"@{{Name='SizeGB';Expression={{[math]::Round($_.Size / 1GB, 2)}}}}")
        tiers = backend.run_ps(tier_cmd)
        tiers = [tiers] if isinstance(tiers, dict) else (tiers or [])
        
        disk_cmd = (f"Get-PhysicalDisk -StoragePoolFriendlyName '{pool_name}' | "
                    f"Select-Object FriendlyName, MediaType, Usage, "
                    f"@{{Name='SizeGB';Expression={{[math]::Round($_.Size / 1GB, 2)}}}}")
        disks = backend.run_ps(disk_cmd)
        disks = [disks] if isinstance(disks, dict) else (disks or [])
        
        topology[pool_name] = {"tiers": tiers, "disks": disks}
        
    return topology

def create_pool(pool_name, disk_names):
    if not disk_names:
        raise ValueError("No disks selected.")
    disks_str = ", ".join([f"'{d}'" for d in disk_names])
    cmd = (f"$disks = Get-PhysicalDisk | Where-Object FriendlyName -in {disks_str}; "
           f"New-StoragePool -FriendlyName '{pool_name}' "
           f"-StorageSubsystemFriendlyName 'Windows Storage*' -PhysicalDisks $disks")
    return backend.run_ps(cmd)

def optimize_pool(pool_name):
    cmd = f"Optimize-StoragePool -FriendlyName '{pool_name}' -AsJob"
    return backend.run_ps(cmd)

def set_media_type(disk_name, media_type):
    cmd = f"Set-PhysicalDisk -FriendlyName '{disk_name}' -MediaType {media_type}"
    return backend.run_ps(cmd)

def create_tier(pool_name, tier_name, media_type):
    cmd = (f"New-StorageTier -StoragePoolFriendlyName '{pool_name}' "
           f"-FriendlyName '{tier_name}' -MediaType {media_type}")
    return backend.run_ps(cmd)

def create_virtual_disk(pool_name, vd_name, resiliency_label, columns, interleave_kb, size_gb):
    res_map = {
        "Simple": ("Simple", None),
        "Two-Way Mirror": ("Mirror", 1),
        "Three-Way Mirror": ("Mirror", 2),
        "Single Parity": ("Parity", 1),
        "Dual Parity": ("Parity", 2)
    }
    res_type, redundancy = res_map.get(resiliency_label, ("Simple", None))

    cmd = (f"New-VirtualDisk -StoragePoolFriendlyName '{pool_name}' "
           f"-FriendlyName '{vd_name}' -ResiliencySettingName {res_type}")
    
    if redundancy is not None:
        cmd += f" -PhysicalDiskRedundancy {redundancy}"
    
    if str(columns).lower() != "auto" and str(columns).strip() != "":
        cmd += f" -NumberOfColumns {columns}"
    if str(interleave_kb).lower() != "auto" and str(interleave_kb).strip() != "":
        cmd += f" -Interleave {interleave_kb}KB"
    
    if str(size_gb).lower() == "maximum" or str(size_gb).strip() == "":
        cmd += " -UseMaximumSize"
    else:
        cmd += f" -Size {size_gb}GB"
        
    return backend.run_ps(cmd)