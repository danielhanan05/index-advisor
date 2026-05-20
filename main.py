from __future__ import annotations

import sys
from pathlib import Path

# Keep `python main.py ...` working after moving the backend package under /backend.
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from index_advisor.main import main


if __name__ == "__main__":
    main()
