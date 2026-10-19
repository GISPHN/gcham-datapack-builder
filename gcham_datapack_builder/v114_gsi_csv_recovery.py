# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN
"""Prefer GSI prefectural CSV; recover using official nationwide CSV files.

The GSI download list is populated by JavaScript. If the prefectural links
cannot be discovered, the nationwide CSV datasets offer a deterministic CSV
route before the existing official GeoJSON fallback is used.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from . import supplemental

_APPLIED = False
_NATIONAL_CSV_ROOT = "https://hinanmap.gsi.go.jp/hinanjocp/defaultFtpData/csv"
_NATIONAL_EMERGENCY = f"{_NATIONAL_CSV_ROOT}/mergeFromCity_2.csv"
_NATIONAL_SHELTER = f"{_NATIONAL_CSV_ROOT}/mergeFromCity_1.csv"
_NATIONAL_FIELD = "都道府県名及び市町村名"


def apply_v114_gsi_csv_recovery():
    global _APPLIED
    if _APPLIED:
        return

    cls = supplemental.SupplementalBuilder
    original_info = cls._gsi_info
    original_convert = cls._gsi_csv_to_fgb

    def _gsi_info(self):
        self._gcham_gsi_national_csv = False
        try:
            return original_info(self)
        except Exception as exc:
            # A real publication date is not available from the fallback URLs.
            # Use retrieval date, making the semantics explicit in the log.
            retrieval_date = date.today().strftime("%Y%m%d")
            self._gcham_gsi_national_csv = True
            self.log(
                "GSI都道府県別CSVのURLを特定できなかったため、"
                "国土地理院の全国統合CSVを都道府県で絞り込んで利用します。"
                "（ファイル名の日付はデータ更新日ではなく取得日）"
                f" 詳細: {exc}"
            )
            return retrieval_date, _NATIONAL_EMERGENCY, _NATIONAL_SHELTER

    def _gsi_csv_to_fgb(self, csv_path: Path, out: Path):
        if not getattr(self, "_gcham_gsi_national_csv", False):
            return original_convert(self, csv_path, out)

        # Read the national CSV, verify expected schema, then materialize a
        # prefecture subset for the pre-existing, well-tested CSV writer.
        # Nationwide files are published as UTF-8 with BOM. Do not run the
        # general CP932-first decoder here, because valid UTF-8 can be
        # misdecoded as CP932 without raising an exception.
        try:
            decoded = csv_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            decoded = csv_path.read_text(encoding="cp932")
        rows = list(csv.DictReader(decoded.splitlines()))
        if not rows:
            raise RuntimeError(f"GSI全国統合CSVが空です: {csv_path.name}")
        columns = list(rows[0].keys())
        required = {_NATIONAL_FIELD, "施設・場所名", "緯度", "経度"}
        if not required.issubset(columns):
            raise RuntimeError(
                "GSI全国統合CSVの列構成が想定と異なります: "
                + ", ".join(sorted(required - set(columns)))
            )
        subset = [
            row for row in rows
            if str(row.get(_NATIONAL_FIELD) or "").strip().startswith(self.pref_name)
        ]
        if not subset:
            raise RuntimeError(f"GSI全国統合CSVに{self.pref_name}の施設がありません。")

        filtered = csv_path.with_name(f"{csv_path.stem}_{self.pref_code}_filtered.csv")
        # The temporary file is refreshed every time; the source CSV itself
        # remains unchanged and can be reused from the download cache.
        with filtered.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=columns)
            writer.writeheader()
            writer.writerows(subset)
        self.log(
            f"GSI全国統合CSVから{self.pref_name}を抽出: "
            f"{len(rows)}件中{len(subset)}件（{csv_path.name}）"
        )
        try:
            return original_convert(self, filtered, out)
        finally:
            filtered.unlink(missing_ok=True)

    cls._gsi_info = _gsi_info
    cls._gsi_csv_to_fgb = _gsi_csv_to_fgb
    _APPLIED = True
