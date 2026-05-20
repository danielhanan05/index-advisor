from __future__ import annotations

"""Production/local launcher for the packaged Database Index Advisor app.

This file is intentionally separate from main.py:
- main.py remains the developer/CLI entry point.
- run_app.py is the end-user launcher used by PyInstaller/Nuitka.

It starts FastAPI on a local port and opens the browser automatically. The
React production build is served by FastAPI from backend/index_advisor/web.
"""

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


APP_MODULE = "index_advisor.api.main:app"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def _runtime_base_dir() -> Path:
    # PyInstaller one-folder/one-file support. In normal source mode this is the
    # folder containing this launcher.
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def _add_backend_to_path() -> None:
    backend_dir = _runtime_base_dir() / "backend"
    if backend_dir.exists() and str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) != 0


def _choose_port(host: str, preferred_port: int) -> int:
    if _port_is_free(host, preferred_port):
        return preferred_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _open_browser_when_ready(url: str) -> None:
    # Give uvicorn a small startup window before opening the browser.
    time.sleep(1.2)
    webbrowser.open(url)


def main() -> None:
    _add_backend_to_path()

    host = os.getenv("INDEX_ADVISOR_HOST", DEFAULT_HOST)
    preferred_port = int(os.getenv("INDEX_ADVISOR_PORT", str(DEFAULT_PORT)))
    port = _choose_port(host, preferred_port)
    url = f"http://{host}:{port}"

    if os.getenv("INDEX_ADVISOR_NO_BROWSER", "").strip().lower() not in {"1", "true", "yes", "y"}:
        threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()

    print(f"Database Index Advisor is starting at {url}")
    print("Press Ctrl+C to stop the local server.")

    uvicorn.run(
        APP_MODULE,
        host=host,
        port=port,
        reload=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
