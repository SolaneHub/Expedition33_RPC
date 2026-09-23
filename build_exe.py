import subprocess
import sys


def build():
    print("Building Expedition33_RPC.exe...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name",
        "Expedition33_RPC",
        "--icon",
        "src/expedition33_rpc/assets/icon.ico",
        "--add-data",
        "src/expedition33_rpc/assets/icon.png;expedition33_rpc/assets",
        "--paths",
        "src",
        "--clean",
        "main.py",
    ]
    print("Command:", " ".join(cmd))
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print("\n=============================================")
        print(" BUILD SUCCESSFUL! ")
        print(" Binary location: dist\\Expedition33_RPC.exe")
        print("=============================================")
    else:
        print(f"Build failed with exit code: {res.returncode}")
        sys.exit(res.returncode)


if __name__ == "__main__":
    build()
