import os
import sys


def get_resource_path(filename: str) -> str:
    """Resolves resource path across development environments and PyInstaller frozen runtime."""
    if getattr(sys, "frozen", False):
        base_meipass = getattr(sys, "_MEIPASS", None)
        if base_meipass:
            bundled_pkg = os.path.join(base_meipass, "expedition33_rpc", "assets", filename)
            if os.path.exists(bundled_pkg):
                return bundled_pkg
            flat_bundled = os.path.join(base_meipass, filename)
            if os.path.exists(flat_bundled):
                return flat_bundled

        exe_dir = os.path.dirname(sys.executable)
        candidate = os.path.join(exe_dir, filename)
        if os.path.exists(candidate):
            return candidate

    module_dir = os.path.dirname(os.path.abspath(__file__))
    candidate_parent = os.path.normpath(os.path.join(module_dir, "..", "assets", filename))
    if os.path.exists(candidate_parent):
        return candidate_parent
    candidate_pkg = os.path.normpath(os.path.join(module_dir, "assets", filename))
    if os.path.exists(candidate_pkg):
        return candidate_pkg

    return filename
