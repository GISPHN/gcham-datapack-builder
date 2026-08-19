# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

from qgis.core import QgsGeometry

from . import v112_followup

# Official parent municipality codes for Japan's ordinance-designated cities.
# N03 ward records identify the parent by N03_003 (郡・政令都市名), while
# N03_004 contains the ward name. Keeping the parent code explicit avoids
# incorrect prefix inference (e.g. Shizuoka City and Hamamatsu City both use
# ward codes beginning with 221xx).
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

    N03 hierarchy:
      N03_003 = 郡・政令都市名 (parent designated city for ward records)
      N03_004 = 市区町村名 (ward name for designated-city ward records)

    The previous test implementation incorrectly expected N03_004/N03_005
    and inferred parent codes from the first three digits of ward codes.
    """
    grouped: dict[str, dict] = {}
    for municipality in municipalities:
        attrs = municipality.attributes
        city_name = str(attrs.get("N03_003") or "").strip()
        ward_name = str(attrs.get("N03_004") or "").strip()
        ward_code = str(municipality.code).strip()

        city_code = _DESIGNATED_CITY_CODES.get(city_name)
        if city_code is None:
            continue
        if not ward_name or len(ward_code) != 5 or not ward_code.isdigit():
            continue
        # A designated-city child must be a ward rather than the parent city
        # itself. N03_003 provides the parent city name, while N03_004 is the ward.
        if ward_name == city_name:
            continue

        entry = grouped.setdefault(
            city_code,
            {"name": city_name, "wards": [], "geometries": []},
        )
        entry["wards"].append(ward_code)
        entry["geometries"].append(QgsGeometry(municipality.geometry))

    # Require at least two distinct wards so an accidental single record cannot
    # create a misleading parent-city outline.
    return {
        city_code: entry
        for city_code, entry in grouped.items()
        if len(set(entry["wards"])) >= 2
    }


def apply_cityfix() -> None:
    # The build wrapper created in v112_followup resolves this module-global
    # function at runtime, so replacing it here fixes both all-prefecture runs
    # and ward-only selected runs without another build wrapper.
    v112_followup._designated_city_groups = _designated_city_groups_fixed
