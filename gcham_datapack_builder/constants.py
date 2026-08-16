# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

PLUGIN_NAME = "G-CHAM Data Pack Builder"
CENSUS_YEAR = 2020
N03_YEAR = 2026
GEOGRAPHIC_CRS_EPSG = 6668

# JGD2011 / Japan Plane Rectangular CS zone mapping.
# EPSG codes are sequential: zone I=6669 ... zone XIX=6687.
PLANE_RECTANGULAR_ZONE_BY_PREF = {
    "01": 12,  # Hokkaido: main zone; official territory spans XI-XIII
    "02": 10, "03": 10, "04": 10, "05": 10, "06": 10,
    "07": 9, "08": 9, "09": 9, "10": 9, "11": 9, "12": 9,
    "13": 9,  # Tokyo: main area; remote islands span XIV/XVIII/XIX
    "14": 9,
    "15": 8, "16": 7, "17": 7, "18": 6, "19": 8, "20": 8,
    "21": 7, "22": 8, "23": 7, "24": 6, "25": 6, "26": 6,
    "27": 6, "28": 5, "29": 6, "30": 6, "31": 5, "32": 3,
    "33": 5, "34": 3, "35": 3, "36": 4, "37": 4, "38": 4,
    "39": 4, "40": 2, "41": 2, "42": 1, "43": 2, "44": 2,
    "45": 2, "46": 2,  # Kagoshima also has zone I islands
    "47": 15,  # Okinawa main island; prefecture spans XV-XVII
}

MULTI_ZONE_PREFS = {"01", "13", "46", "47"}

def plane_rectangular_epsg(pref_code: str) -> int:
    zone = PLANE_RECTANGULAR_ZONE_BY_PREF[str(pref_code).zfill(2)]
    return 6668 + zone

PREFECTURES = [
    ("01", "北海道"), ("02", "青森県"), ("03", "岩手県"), ("04", "宮城県"),
    ("05", "秋田県"), ("06", "山形県"), ("07", "福島県"), ("08", "茨城県"),
    ("09", "栃木県"), ("10", "群馬県"), ("11", "埼玉県"), ("12", "千葉県"),
    ("13", "東京都"), ("14", "神奈川県"), ("15", "新潟県"), ("16", "富山県"),
    ("17", "石川県"), ("18", "福井県"), ("19", "山梨県"), ("20", "長野県"),
    ("21", "岐阜県"), ("22", "静岡県"), ("23", "愛知県"), ("24", "三重県"),
    ("25", "滋賀県"), ("26", "京都府"), ("27", "大阪府"), ("28", "兵庫県"),
    ("29", "奈良県"), ("30", "和歌山県"), ("31", "鳥取県"), ("32", "島根県"),
    ("33", "岡山県"), ("34", "広島県"), ("35", "山口県"), ("36", "徳島県"),
    ("37", "香川県"), ("38", "愛媛県"), ("39", "高知県"), ("40", "福岡県"),
    ("41", "佐賀県"), ("42", "長崎県"), ("43", "熊本県"), ("44", "大分県"),
    ("45", "宮崎県"), ("46", "鹿児島県"), ("47", "沖縄県"),
]

STAT_TABLES = [
    ("T001142", "人口及び世帯"),
    ("T001145", "人口移動、就業状態等及び従業地・通学地"),
    ("T001196", "５歳階級別人口"),
    ("T001197", "労働力状態、産業分類及び職業分類別人口（１５歳以上）"),
    ("T001198", "住宅の所有及び建て方"),
    ("T001199", "５年前の常住地及び従業地・通学地等"),
]

ESTAT_URL = (
    "https://www.e-stat.go.jp/gis/statmap-search/data"
    "?datatype=1&statsId={stats_id}&downloadType=2&code={pref_code}"
)
N03_URL = (
    "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/"
    "N03-20260101_{pref_code}_GML.zip"
)

COMMON_FIELDS = ("KEY_CODE", "HTKSYORI", "HTKSAKI", "GASSAN")
BASE_STATS_ID = "T001142"
DERIVED_SPECS = [
    ("T001142004", "T001142001", "０～１４歳人口　総数_割合100"),
    ("T001142010", "T001142001", "１５～６４歳人口　総数_割合100"),
    ("T001142019", "T001142001", "６５歳以上人口　総数_割合100"),
]

SETTINGS_PREFIX = "gcham_datapack_builder"
