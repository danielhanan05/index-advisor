from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from psycopg import sql


_IDENT_SAFE_RE = re.compile(r"[^a-zA-Z0-9_]+")
_PG_IDENT_MAXLEN = 63


@dataclass(frozen=True)
class IndexColumn:
    name: str
    direction: str | None = None

    @property
    def display(self) -> str:
        if self.direction:
            return f"{self.name} {self.direction.upper()}"
        return self.name


def _normalize_ident_piece(s: str) -> str:
    s = (s or "").strip()
    s = _IDENT_SAFE_RE.sub("_", s).strip("_").lower()
    return s or "x"


def _normalize_column_for_name(column: str | IndexColumn) -> str:
    if isinstance(column, IndexColumn):
        suffix = "_desc" if (column.direction or "").upper() == "DESC" else ""
        return f"{column.name}{suffix}"
    return str(column)


def build_deterministic_index_name(table_name: str, columns: list[str | IndexColumn], include_columns: list[str] | None = None) -> str:
    """
    Deterministic, reasonably short, PG-safe identifier.
    Example: idx_advisor_<table>_<col1>_<col2>_<hash6>
    """
    table_part = _normalize_ident_piece(table_name)
    col_part = "_".join(_normalize_ident_piece(_normalize_column_for_name(c)) for c in columns[:3])
    include_part = ""
    if include_columns:
        include_part = "_inc_" + "_".join(_normalize_ident_piece(c) for c in include_columns[:2])
    base = f"idx_advisor_{table_part}_{col_part}{include_part}"

    # Add a small hash to reduce collisions after truncation.
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:6]
    name = f"{base}_{h}"

    if len(name) <= _PG_IDENT_MAXLEN:
        return name

    # Truncate base part and keep hash.
    prefix_max = _PG_IDENT_MAXLEN - (1 + len(h))
    return f"{name[:prefix_max]}_{h}"


def _column_sql(column: str | IndexColumn) -> sql.Composed:
    if isinstance(column, IndexColumn):
        parts: list[sql.SQL | sql.Identifier] = [sql.Identifier(column.name)]
        if column.direction and column.direction.upper() in {"ASC", "DESC"}:
            parts.append(sql.SQL(f" {column.direction.upper()}"))
        return sql.Composed(parts)
    return sql.Composed([sql.Identifier(str(column))])


def create_index_sql(
    *,
    index_name: str,
    schemaname: str,
    table_name: str,
    columns: list[str | IndexColumn],
    include_columns: list[str] | None = None,
    concurrently: bool = True,
    if_not_exists: bool = True,
) -> sql.Composed:
    """
    Build a CREATE INDEX statement with properly quoted identifiers.
    Supports ordered key columns and INCLUDE columns.
    Returns a psycopg.sql object (safe to .as_string(conn)).
    """
    if not columns:
        raise ValueError("columns must not be empty")

    parts: list[sql.SQL | sql.Identifier | sql.Composed] = [sql.SQL("CREATE INDEX")]
    if concurrently:
        parts.append(sql.SQL(" CONCURRENTLY"))
    if if_not_exists:
        parts.append(sql.SQL(" IF NOT EXISTS"))

    parts.extend(
        [
            sql.SQL(" "),
            sql.Identifier(index_name),
            sql.SQL(" ON "),
            sql.Identifier(schemaname),
            sql.SQL("."),
            sql.Identifier(table_name),
            sql.SQL(" ("),
            sql.SQL(", ").join(_column_sql(c) for c in columns),
            sql.SQL(")"),
        ]
    )

    safe_include = [c for c in (include_columns or []) if c]
    if safe_include:
        parts.extend(
            [
                sql.SQL(" INCLUDE ("),
                sql.SQL(", ").join(sql.Identifier(c) for c in safe_include),
                sql.SQL(")"),
            ]
        )

    parts.append(sql.SQL(";"))
    return sql.Composed(parts)


def normalize_for_hypopg(create_index_sql_text: str) -> str:
    """
    hypopg_create_index() doesn't support CONCURRENTLY, and IF NOT EXISTS is unnecessary.
    """
    s = create_index_sql_text
    s = re.sub(r"\bCONCURRENTLY\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bIF\s+NOT\s+EXISTS\b", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()
