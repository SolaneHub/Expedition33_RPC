import os
import subprocess
import sys


def check_target_lock(target_path: str) -> None:
    """Verifies that the target binary is not locked by another running process."""
    if os.path.exists(target_path):
        try:
            with open(target_path, "a+b"):
                pass
        except OSError as e:
            print(f"Error: Target '{target_path}' is locked: {e}", file=sys.stderr)
            sys.exit(1)


def build() -> None:
    expected_exe = (
        "dist/Expedition33_RPC.exe" if sys.platform == "win32" else "dist/Expedition33_RPC"
    )
    check_target_lock(expected_exe)
    print("Building Expedition33_RPC.exe...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--noconsole",
        "--name",
        "Expedition33_RPC",
        "--icon",
        "src/expedition33_rpc/assets/icon.ico",
        "--add-data",
        f"src/expedition33_rpc/assets/icon.png{os.pathsep}expedition33_rpc/assets",
        "--add-data",
        f"src/expedition33_rpc/assets/bridge.zip{os.pathsep}expedition33_rpc/assets",
        "--add-data",
        f"src/expedition33_rpc/assets/game_data.json{os.pathsep}expedition33_rpc/assets",
        "--hidden-import",
        "expedition33_rpc.core.platform",
        "--hidden-import",
        "expedition33_rpc.core.presence",
        "--hidden-import",
        "expedition33_rpc.detection.compat_paths",
        "--hidden-import",
        "expedition33_rpc.detection.game_data",
        "--hidden-import",
        "expedition33_rpc.core.smoke",
        "--hidden-import",
        "expedition33_rpc.detection.save_reader",
        "--paths",
        "src",
        "--clean",
        "main.py",
    ]
    print("Command:", " ".join(cmd))
    res = subprocess.run(cmd, stdin=subprocess.DEVNULL)
    if res.returncode == 0 and os.path.exists(expected_exe) and os.path.getsize(expected_exe) > 0:
        print("\n=============================================")
        print(" BUILD SUCCESSFUL! ")
        print(f" Binary location: {expected_exe}")
        print("=============================================")
    else:
        if res.returncode != 0:
            print(f"Build failed with exit code: {res.returncode}")
            sys.exit(res.returncode)
        else:
            print(f"Build failed: output binary '{expected_exe}' was not produced or is empty.")
            sys.exit(1)


if __name__ == "__main__":
    build()
