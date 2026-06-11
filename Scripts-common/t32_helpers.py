import subprocess
import time
import os
from datetime import datetime
import lauterbach.trace32.rcl as t32


def elapsed_since(start):
    """Return a human-readable elapsed-time string like ``30s`` or ``2m05s``."""
    s = time.time() - start
    if s >= 60:
        return f"{int(s//60)}m{int(s%60):02d}s"
    return f"{s:.0f}s"


def start_trace32(trace32_exe, config_file):
    proc = subprocess.Popen([trace32_exe, "-b", "-c", config_file])
    time.sleep(2.0)
    return proc


def connect_dbg(timeout=600):
    try:
        dbg = t32.connect(node="localhost", port=20000, timeout=timeout)
    except TypeError:
        dbg = t32.connect(node="localhost", port=20000)
    return dbg


def wrap_dbg_with_logger(dbg, api_log_file):
    original_cmd = dbg.cmd

    def logged_cmd(cmd_str):
        with open(api_log_file, "a", encoding="utf-8") as f:
            f.write(f"CMD :: {cmd_str}\n")
        return original_cmd(cmd_str)

    dbg.cmd = logged_cmd
    return dbg


def read_area_content(dbg, area_name="A000"):
    """Read TRACE32 AREA window content and return it as a string.

    Uses ``AREA.SAVE`` to write the window contents to a temporary file,
    reads it back, then removes the file.  Returns empty string on failure.
    """
    import tempfile
    tmp_dir = tempfile.gettempdir()
    tmp_file = os.path.join(tmp_dir, f"t32_area_read_{area_name}_{int(time.time())}.txt")
    try:
        t32_path = tmp_file.replace('\\', '/')
        dbg.cmd(f'AREA.SAVE {area_name} "{t32_path}"')
        time.sleep(0.3)
        if os.path.exists(tmp_file):
            with open(tmp_file, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        return ""
    except Exception:
        return ""
    finally:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass


def dump_area(dbg, api_log_file, tag):
    """Save TRACE32 AREA window (default A000) content into api_log_file.

    TRACE32 commands like ``AREA`` or ``AREA.List`` only open UI windows and
    do **not** return their text content via the RCL API.  The correct approach
    (per ide_ref.pdf) is ``AREA.SAVE [<area_name>] <file>`` which writes the
    full window contents to a file on the host.
    """
    import tempfile

    # give TRACE32 a short moment to update UI state
    time.sleep(0.5)

    tmp_dir = tempfile.gettempdir()
    timestamp = int(time.time())
    out_parts = []

    # --- primary method: AREA.SAVE for the default area A000 ---------------
    area_name = "A000"
    try:
        tmp_file = os.path.join(tmp_dir, f"t32_area_{area_name}_{tag}_{timestamp}.txt")
        # TRACE32 expects forward slashes; quote in case the path contains spaces
        t32_path = tmp_file.replace('\\', '/')
        dbg.cmd(f'AREA.SAVE {area_name} "{t32_path}"')
        time.sleep(0.3)

        if os.path.exists(tmp_file):
            with open(tmp_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            os.remove(tmp_file)
            out_parts.append(f"// AREA [{area_name}] content:\n{content}")
        else:
            out_parts.append(f"// AREA.SAVE {area_name}: file not created")
    except Exception as e:
        out_parts.append(f"// AREA.SAVE {area_name} failed: {e}")

    # --- fallback: try to get any text from AREA.List ----------------------
    if not out_parts or all("content:" not in p for p in out_parts):
        try:
            resp = dbg.cmd('AREA.List')
            if resp:
                out_parts.append(f"// AREA.List output:\n{resp}")
        except Exception:
            pass

    full_out = '\n'.join(out_parts)

    # Always write to the log file
    with open(api_log_file, 'a', encoding='utf-8') as f:
        f.write(f"// AREA RAW [{tag}] (AREA.SAVE method)\n")
        f.write(f"// AREA DUMP [{tag}] start\n")
        f.write(full_out + '\n')
        f.write(f"// AREA DUMP [{tag}] end\n")

    # If there is actual AREA content, also print to the terminal in green
    has_content = any("content:" in p for p in out_parts)
    if has_content:
        # Extract the real content (text after the "// AREA [A000] content:\n" marker)
        for p in out_parts:
            if p.startswith("// AREA [A000] content:"):
                real_content = p.split("content:\n", 1)[-1]
                if real_content.strip():
                    green = "\033[92m"
                    reset = "\033[0m"
                    print(f"{green}[AREA {tag}]{reset}")
                    for line in real_content.split('\n'):
                        print(f"{green}{line}{reset}")
                break
