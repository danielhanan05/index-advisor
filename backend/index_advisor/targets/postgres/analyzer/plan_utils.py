from __future__ import annotations

import re
from typing import Any, Generator


def _normalize_explain_json(plan_json: Any) -> dict[str, Any]:
    # EXPLAIN (FORMAT JSON) returns: [ { "Plan": {...}, ... } ]
    if isinstance(plan_json, list) and plan_json and isinstance(plan_json[0], dict):
        return plan_json[0]
    if isinstance(plan_json, dict):
        return plan_json
    return {}


def walk_plan_nodes(plan_json: Any) -> Generator[dict[str, Any], None, None]:
    root = _normalize_explain_json(plan_json)
    plan = root.get("Plan") if isinstance(root, dict) else None
    if not isinstance(plan, dict):
        return

    def _walk(node: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
        yield node

        for child in node.get("Plans", []) or []:
            if isinstance(child, dict):
                yield from _walk(child)

        # Handle InitPlan/SubPlan (each element may contain {"Plan": {...}})
        for key in ("InitPlan", "SubPlan"):
            for sub in node.get(key, []) or []:
                if isinstance(sub, dict):
                    sub_plan = sub.get("Plan")
                    if isinstance(sub_plan, dict):
                        yield from _walk(sub_plan)

    yield from _walk(plan)


def find_scan_nodes(plan_json: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in walk_plan_nodes(plan_json):
        node_type = node.get("Node Type")
        if node_type in {"Seq Scan", "Parallel Seq Scan"}:
            out.append(node)
    return out


def extract_total_cost(plan_json: Any) -> float | None:
    root = _normalize_explain_json(plan_json)
    plan = root.get("Plan") if isinstance(root, dict) else None
    if not isinstance(plan, dict):
        return None
    cost = plan.get("Total Cost")
    try:
        return float(cost) if cost is not None else None
    except Exception:
        return None


def extract_plan_rows(plan_node: dict[str, Any]) -> float | None:
    rows = plan_node.get("Plan Rows")
    try:
        return float(rows) if rows is not None else None
    except Exception:
        return None


_FILTER_COL_RE = re.compile(
    r"""
    (?<![a-zA-Z0-9_\.])
    (?P<col>[a-zA-Z_][a-zA-Z0-9_]*)
    (?![a-zA-Z0-9_])
    \s*
    (?:
        =|>=|<=|<>|<|>
        |IN\s*\(
        |IS\s+NOT\s+NULL
        |IS\s+NULL
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_filter_columns(filter_text: str | None) -> list[str]:
    if not filter_text:
        return []
    cols: list[str] = []
    for m in _FILTER_COL_RE.finditer(filter_text):
        col = m.group("col")
        if col.upper() in {"AND", "OR", "NOT", "NULL", "TRUE", "FALSE"}:
            continue
        cols.append(col)

    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

