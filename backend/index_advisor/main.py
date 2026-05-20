from __future__ import annotations

import argparse
import logging
from pathlib import Path

from index_advisor.db import get_target_row, test_connections
from index_advisor.utils.logging_utils import configure_logging
from index_advisor.storage.migrations import apply_storage_migrations
from index_advisor.storage.retention import apply_storage_retention
from index_advisor.targets.registry import get_adapter


logger = logging.getLogger(__name__)


def migrate() -> None:
    apply_storage_migrations()
    apply_storage_retention(force=True)

def _adapter_for_target(target_id: int | None = None):
    target = get_target_row(target_id)
    return get_adapter(target.get("engine") if target else "postgres")


def run_collect(target_id: int | None = None) -> None:
    adapter = _adapter_for_target(target_id)
    run_id = adapter.collect(target_id=target_id)
    logger.info("Collect finished. engine=%s run_id=%s", adapter.engine, run_id)


def run_analyze(target_id: int | None = None) -> None:
    adapter = _adapter_for_target(target_id)
    stored = adapter.analyze_latest_run(target_id=target_id)
    logger.info("Analyze finished. engine=%s recommendations_stored=%s", adapter.engine, stored)
    logger.info("Storage retention finished. %s", apply_storage_retention(force=True).as_dict())


def run_all(target_id: int | None = None) -> None:
    adapter = _adapter_for_target(target_id)
    run_id = adapter.collect(target_id=target_id)
    logger.info("Collect finished. engine=%s run_id=%s", adapter.engine, run_id)

    stored = adapter.analyze_latest_run(target_id=target_id)
    logger.info("Run finished. engine=%s recommendations_stored=%s", adapter.engine, stored)
    logger.info("Storage retention finished. %s", apply_storage_retention(force=True).as_dict())


def run_api(host: str, port: int, reload: bool) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: uvicorn. Install with: pip install fastapi uvicorn"
        ) from exc

    uvicorn.run(
        "index_advisor.api.main:app",
        host=host,
        port=port,
        reload=reload,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="index_advisor")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="Run storage SQL migrations")
    collect_p = sub.add_parser("collect", help="Collect stats and plans from target DB")
    collect_p.add_argument("--target-id", type=int, default=None)
    analyze_p = sub.add_parser("analyze", help="Analyze latest completed collection run")
    analyze_p.add_argument("--target-id", type=int, default=None)
    run_p = sub.add_parser("run", help="Collect and then analyze")
    run_p.add_argument("--target-id", type=int, default=None)
    sub.add_parser("test", help="Test DB connections")

    api = sub.add_parser("api", help="Run the FastAPI server")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--reload", action="store_true")

    return p


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    args = build_parser().parse_args(argv)

    if args.command == "migrate":
        migrate()
    elif args.command == "collect":
        run_collect(target_id=args.target_id)
    elif args.command == "analyze":
        run_analyze(target_id=args.target_id)
    elif args.command == "run":
        run_all(target_id=args.target_id)
    elif args.command == "test":
        test_connections()
    elif args.command == "api":
        run_api(args.host, args.port, args.reload)
    else:
        raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()