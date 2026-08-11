import subprocess
import json

log_callback = None

def run_ps(command):
    if log_callback:
        log_callback(f"[CMD] {command}")
        
    ps_command = f"{command} | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
            capture_output=True,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,  # Prevents input stream deadlocks
            creationflags=0x08000000   # Detaches the process (CREATE_NO_WINDOW)
        )
        output = result.stdout.strip()
        
        if log_callback:
            if output:
                # Truncate visually massive JSON blobs in the log for readability
                log_text = output[:300] + "... [Output Truncated]" if len(output) > 300 else output
                log_callback(f"[OUT] {log_text}\n")
            else:
                log_callback("[OUT] Execution completed with no output.\n")
                
        if output:
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return output
        return None
    except subprocess.CalledProcessError as e:
        err = e.stderr.strip()
        if log_callback:
            log_callback(f"[ERR] {err}\n")
        raise RuntimeError(f"PowerShell error: {err}")