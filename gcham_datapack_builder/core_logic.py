# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .constants import COMMON_FIELDS


@dataclass(frozen=True)
class ColumnDef:
    stats_id: str
    code: str
    label: str


@dataclass(frozen=True)
class TableHeader:
    stats_id: str
    codes: tuple[str, ...]
    labels: tuple[str, ...]

    def columns(self) -> list[ColumnDef]:
        return [
            ColumnDef(self.stats_id, code, label or code)
            for code, label in zip(self.codes[4:], self.labels[4:])
        ]


def load_preset_config(plugin_dir: Path) -> dict:
    path = plugin_dir / "config" / "gcham_columns.json"
    return json.loads(path.read_text(encoding="utf-8"))


def estat_archive_name(stats_id: str, pref_code: str) -> str:
    return f"tbl{stats_id}Q{pref_code}.zip"


def n03_archive_name(pref_code: str) -> str:
    return f"N03-20260101_{pref_code}_GML.zip"


def _find_txt_member(zf: zipfile.ZipFile) -> str:
    members = [n for n in zf.namelist() if not n.endswith("/")]
    txt = [n for n in members if n.lower().endswith((".txt", ".csv"))]
    if not txt:
        raise ValueError("e-Stat ZIP内に .txt/.csv が見つかりません。")
    # Prefer the member whose stem matches the archive convention.
    return sorted(txt, key=lambda n: ("tbl" not in Path(n).name.lower(), len(n)))[0]


def read_estat_header(zip_path: Path, stats_id: str) -> TableHeader:
    with zipfile.ZipFile(zip_path) as zf:
        member = _find_txt_member(zf)
        with zf.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="cp932", newline="")
            reader = csv.reader(text)
            try:
                codes = tuple(v.strip() for v in next(reader))
                labels = tuple(v.strip() for v in next(reader))
            except StopIteration as exc:
                raise ValueError(f"{zip_path.name}: ヘッダ2行を読み取れません。") from exc
    if len(codes) != len(labels):
        raise ValueError(f"{zip_path.name}: 1行目と2行目の列数が一致しません。")
    if tuple(codes[:4]) != COMMON_FIELDS:
        raise ValueError(
            f"{zip_path.name}: 先頭4列が想定と異なります: {codes[:4]}"
        )
    return TableHeader(stats_id=stats_id, codes=codes, labels=labels)


def iter_estat_rows(zip_path: Path) -> Iterator[dict[str, str | None]]:
    with zipfile.ZipFile(zip_path) as zf:
        member = _find_txt_member(zf)
        with zf.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="cp932", newline="")
            reader = csv.reader(text)
            try:
                codes = [v.strip() for v in next(reader)]
                next(reader)  # Japanese label row
            except StopIteration as exc:
                raise ValueError(f"{zip_path.name}: ヘッダが不完全です。") from exc
            for row_no, row in enumerate(reader, start=3):
                if not row:
                    continue
                if len(row) != len(codes):
                    raise ValueError(
                        f"{zip_path.name}:{row_no}: 列数 {len(row)} != {len(codes)}"
                    )
                values = [v.strip() for v in row]
                if not values[0]:
                    continue
                yield {
                    code: (value if value != "" else None)
                    for code, value in zip(codes, values)
                }


_NULL_TOKENS = {"", "*", "***", "X", "x", "-", "－"}


def parse_stat_value(value: str | None):
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if s in _NULL_TOKENS:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            f = float(s)
        except ValueError:
            return s
        if math.isfinite(f):
            return f
    return s


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def merge_values(base: dict[str, object], additions: Iterable[dict[str, object]], value_codes: Iterable[str]) -> dict[str, object]:
    """Merge additive numeric values following qgis-japan-mesh semantics.

    Values which are NULL in a suppressed source mesh are ignored. Non-numeric
    values are not arithmetically combined. This is intentionally conservative.
    """
    out = dict(base)
    for add in additions:
        for code in value_codes:
            v = add.get(code)
            if v is None:
                continue
            current = out.get(code)
            if current is None:
                # For a suppressed source row an isolated numeric value can be
                # safely carried only if the destination has no official value.
                out[code] = v
            elif is_number(current) and is_number(v):
                out[code] = current + v
            # Strings/non-numeric values keep the destination value.
    return out


def make_unique_labels(columns: list[ColumnDef]) -> dict[str, str]:
    counts: dict[str, int] = {}
    for col in columns:
        counts[col.label] = counts.get(col.label, 0) + 1
    result = {}
    for col in columns:
        result[col.code] = col.label if counts[col.label] == 1 else f"{col.label}_{col.code}"
    return result


def normalize_key_code(code: str) -> str:
    s = re.sub(r"\D", "", str(code))
    if len(s) != 10:
        raise ValueError(f"250mメッシュKEY_CODEは10桁である必要があります: {code!r}")
    return s


def mesh250_bbox(code: str) -> tuple[float, float, float, float]:
    """Convert a 10-digit JIS X 0410 1/4 mesh code to lon/lat bbox.

    Returns west, south, east, north in geographic coordinates.
    """
    c = normalize_key_code(code)
    p = int(c[:2])
    q = int(c[2:4])
    r = int(c[4])
    s = int(c[5])
    t = int(c[6])
    u = int(c[7])
    half = int(c[8])
    quarter = int(c[9])
    if half not in (1, 2, 3, 4) or quarter not in (1, 2, 3, 4):
        raise ValueError(f"不正な分割メッシュ番号: {code}")

    south = p * (2.0 / 3.0) + r * (5.0 / 60.0) + t * (30.0 / 3600.0)
    west = 100.0 + q + s * (7.5 / 60.0) + u * (45.0 / 3600.0)

    half_h = 15.0 / 3600.0
    half_w = 22.5 / 3600.0
    if half in (3, 4):
        south += half_h
    if half in (2, 4):
        west += half_w

    q_h = 7.5 / 3600.0
    q_w = 11.25 / 3600.0
    if quarter in (3, 4):
        south += q_h
    if quarter in (2, 4):
        west += q_w

    return west, south, west + q_w, south + q_h


def mesh250_center(code: str) -> tuple[float, float]:
    west, south, east, north = mesh250_bbox(code)
    return (west + east) / 2.0, (south + north) / 2.0


def safe_ratio(numerator, denominator):
    if not is_number(numerator) or not is_number(denominator) or denominator == 0:
        return None
    try:
        value = (Decimal(str(numerator)) / Decimal(str(denominator))) * Decimal("100")
        # 「小数第2位を四捨五入」: 小数第1位まで保持。
        return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ZeroDivisionError):
        return None


def split_gassan(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in str(value).split(";") if v.strip()]


def ascii_admin_filename(muni_code: str) -> str:
    return f"n03_{muni_code}_admin.fgb"


def ascii_population_filename(muni_code: str) -> str:
    return f"census2020_{muni_code}_pop250m.fgb"


def ascii_pref_population_filename(pref_code: str) -> str:
    return f"census2020_{pref_code}_pop250m.fgb"
