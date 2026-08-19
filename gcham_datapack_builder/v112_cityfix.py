# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

from qgis.core import QgsGeometry

from . import v112_followup

# Parent municipality codes for Japan's ordinance-designated cities.
# The code is mapped from the parent city name instead of inferred from ward
# codes. Prefix inference is unsafe in Shizuoka Prefecture because Shizuoka
# City and Hamamatsu City ward codes both begin with 221.
_DESIGNATED_CITY_CODES = {
    "札幌市": "01100",
    "仙台市": "04100",
    "さいたま市": "11100",
    "千葉市": "12100",
    "横浜市": "14100",
    "川崎市": "14130",
    "相模原市": "14150",
    "新潟市": "15100",
    "静岡市": "22100",
    "浜松市": "22130",
    "名古屋市": "23100",
    "京都市": "26100",
    "大阪市": "27100",
    "堺市": "27140",
    "神戸市": "28100",
    "岡山市": "33100",
    "広島市": "34100",
    "北九州市": "40100",
    "福岡市": "40130",
    "熊本市": "43100",
}


def _designated_city_groups_fixed(municipalities):
    """Group N03 ward polygons by their ordinance-designated parent city.

    Current N03 schema (2024+):
      N03_004 = 市区町村名 (parent ordinance-designated city)
      N03_005 = 政令指定都市の行政区名 (ward)

    Older N03 products used N03_003 as 郡・政令都市名 and N03_004 as the
    child municipality/ward. A fallback for that schema is retained so cached
    older N03 data do not break the plugin.
    """
    grouped: dict[str, dict] = {}

    for municipality in municipalities:
        attrs = municipality.attributes
        n03_003 = str(attrs.get("N03_003") or "").strip()
        n03_004 = str(attrs.get("N03_004") or "").strip()
        n03_005 = str(attrs.get("N03_005") or "").strip()
        ward_code = str(municipality.code).strip()

        # Current products: city in N03_004, ward in N03_005.
        if n03_005 and n03_004 in _DESIGNATED_CITY_CODES:
            city_name = n03_004
            ward_name = n03_005
        # Backward-compatible fallback for older products.
        elif n03_003 in _DESIGNATED_CITY_CODES and n03_004:
            city_name = n03_003
            ward_name = n03_004
        else:
            continue

        city_code = _DESIGNATED_CITY_CODES[city_name]
        if not ward_name or len(ward_code) != 5 or not ward_code.isdigit():
            continue

        entry = grouped.setdefault(
            city_code,
            {"name": city_name, "wards": [], "geometries": []},
        )
        entry["wards"].append(ward_code)
        entry["geometries"].append(QgsGeometry(municipality.geometry))

    return {
        city_code: entry
        for city_code, entry in grouped.items()
        if len(set(entry["wards"])) >= 2
    }


def apply_cityfix() -> None:
    # v112_followup's build wrapper resolves this function at runtime.
    v112_followup._designated_city_groups = _designated_city_groups_fixed
