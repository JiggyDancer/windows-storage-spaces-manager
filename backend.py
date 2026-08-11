import subprocess
import json

log_callback = None
LOG_LEVEL = "INFO"  # Can be set by GUI later: "DEBUG", "INFO", "WARN", "ERROR"

def run_ps(command, timeout=30, log_level="INFO"):
    """
    Execute PowerShell command and return parsed JSON output.
    Logs command and output via log_callback if available.
    """
    if log_callback and LOG_LEVEL in ["INFO", "DEBUG"]:
        log_callback(f"[CMD] {command}")

    # Ensure objects are flattened to avoid JSON serialization issues
    ps_command = f"{command} | ForEach-Object {{ $_ | Select-Object * -ExcludeProperty 'PS*' }} | ConvertTo-Json -Compress"

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
            capture_output=True,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            timeout=timeout
        )
        output = result.stdout.strip()

        if log_callback and LOG_LEVEL in ["INFO", "DEBUG"]:
            if output:
                log_text = output[:300] + "... [Output Truncated]" if len(output) > 300 else output
                log_callback(f"[OUT] {log_text}\n")
            else:
                log_callback("[OUT] Execution completed with no output.\n")

        if not output:
            return []  # Return empty list for consistency

        try:
            data = json.loads(output)
            return data
        except json.JSONDecodeError:
            if log_callback and LOG_LEVEL in ["WARN", "ERROR"]:
                log_callback(f"[ERR] Failed to parse JSON: {output[:200]}...\n")
            # Return raw output as fallback
            return output

    except subprocess.TimeoutExpired:
        err_msg = f"PowerShell command timed out after {timeout} seconds: {command}"
        if log_callback:
            log_callback(f"[ERR] {err_msg}\n")
        raise RuntimeError(err_msg)

    except subprocess.CalledProcessError as e:
        err = e.stderr.strip()
        if log_callback:
            log_callback(f"[ERR] {err}\n")
        raise RuntimeError(f"PowerShell error: {err}")