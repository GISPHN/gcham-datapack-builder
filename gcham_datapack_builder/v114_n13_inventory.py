# SPDX-License-Identifier: GPL-2.0-or-later
"""Skip unprovided N13 2024 first meshes using the official inventory."""
from __future__ import annotations

import re
from . import supplemental
from . import v113_roadfix
from . import qgis_io

_APPLIED = False
LIST_URL = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N13-2024.html"
_FILENAME = re.compile(r"N13-24_([0-9]{4})_SHP\\.zip", re.IGNORECASE)


def _published_meshes(builder):
    content, _headers = builder._request_bytes(LIST_URL)
    html = builder._decode_web_text(content)
    codes = set(_FILENAME.findall(html))
    if not codes:
        # Never silently treat an unavailable or changed inventory as no roads.
        raise RuntimeError(
            "国土数値情報の公式N13-2024公開メッシュ一覧を解析できません。"
            "道路データは未作成です。"
        )
    return codes


def apply_v114_n13_inventory():
    global _APPLIED
    if _APPLIED:
        return
    def build_roads(self):
        candidates = sorted(set(supplemental.first_mesh_codes(self.pref_geometry)))
        published = _published_meshes(self)
        available = [code for code in candidates if code in published]
        omitted = [code for code in candidates if code not in published]
        self.log(f"道路N13候補メッシュ: {len(candidates)}件")
        self.log("道路N13公式未提供のため除外: " +
                 (", ".join(omitted) if omitted else "なし"))
        self.log(f"道路N13取得対象: {len(available)}件 / " + ", ".join(available))
        if not available:
            raise RuntimeError("この区域に公式提供済みN13道路メッシュがありません。")
        sources = []
        for code in available:
            self.check_cancelled()
            # An actual error for a published ZIP must still propagate.
            sources.extend(self._ksj_vectors("N13", "24", f"N13-24_{code}_SHP.zip"))
        road_out = self.data_dir / f"n13_2024_{self.pref_code}_roads.fgb"
        qgis_io.remove_existing_layer_for_path(road_out)
        road_out.unlink(missing_ok=True)
        v113_roadfix._write_roads_fast(
            sources, road_out, self.target_epsg, self.pref_geometry,
            self.log, self.check_cancelled
        )
        return [supplemental.SupplementalResult(
            road_out, "道路_2024_国土数値情報", "交通", "road"
        )]
    build_roads._gcham_v114_inventory = True
    supplemental.SupplementalBuilder.build_roads = build_roads
    _APPLIED = True
