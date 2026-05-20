from __future__ import annotations

"""Build helper for creating a packaging-ready project tree.

What it does:
1. Runs the React production build.
2. Copies frontend/dist into backend/index_advisor/web so FastAPI can serve it.
3. Optionally builds a PyInstaller one-folder executable when --pyinstaller is used.

Run from the repository root:
    python packaging/build_release.py
    python packaging/build_release.py --pyinstaller
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
BACKEND_WEB = ROOT / "backend" / "index_advisor" / "web"


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def build_frontend() -> None:
    if not (FRONTEND_DIR / "package.json").exists():
        raise RuntimeError("frontend/package.json was not found")

    npm_cmd = "npm.cmd" if sys.platform.startswith("win") else "npm"
    if not (FRONTEND_DIR / "node_modules").exists():
        run([npm_cmd, "ci"], cwd=FRONTEND_DIR)
    run([npm_cmd, "run", "build"], cwd=FRONTEND_DIR)

    if not (FRONTEND_DIST / "index.html").exists():
        raise RuntimeError("React build did not create frontend/dist/index.html")


def copy_frontend_to_backend() -> None:
    if BACKEND_WEB.exists():
        shutil.rmtree(BACKEND_WEB)
    shutil.copytree(FRONTEND_DIST, BACKEND_WEB)
    print(f"Copied {FRONTEND_DIST} -> {BACKEND_WEB}")


def _add_data_arg(source: Path, destination: str) -> str:
    """Return a PyInstaller --add-data value for the current OS."""
    separator = ";" if sys.platform.startswith("win") else ":"
    return f"{source}{separator}{destination}"


def build_pyinstaller() -> None:
    """Build a one-folder executable that includes backend code and runtime data.

    Important: run_app.py imports the FastAPI app through Uvicorn. Without the
    backend path/hidden imports, PyInstaller may build an executable that starts
    but then fails with: ModuleNotFoundError: No module named 'index_advisor'.
    """
    run([
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        "IndexAdvisor",
        "--onedir",
        "--clean",
        "--paths",
        str(ROOT / "backend"),
        "--hidden-import",
        "index_advisor.api.main",
        "--collect-submodules",
        "index_advisor",
        "--add-data",
        _add_data_arg(ROOT / "backend" / "index_advisor" / "web", "index_advisor/web"),
        "--add-data",
        _add_data_arg(ROOT / "backend" / "index_advisor" / "storage", "index_advisor/storage"),
        "run_app.py",
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pyinstaller", action="store_true", help="Also build a PyInstaller one-folder executable")
    args = parser.parse_args()

    build_frontend()
    copy_frontend_to_backend()

    if args.pyinstaller:
        build_pyinstaller()

    print("Packaging prep finished.")


if __name__ == "__main__":
    main()
