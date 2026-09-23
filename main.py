import sys
from pathlib import Path

# Add src to sys.path for direct execution from repository root
sys.path.insert(0, str(Path(__file__).parent / "src"))

from expedition33_rpc.app import main

if __name__ == "__main__":
    main()
