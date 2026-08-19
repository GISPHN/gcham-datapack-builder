# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import gc
import json
from datetime import date
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

from . import dialog as dialog_module
from . import processor as processor_module
from . import qgis_io
from . import supplemental
from . import v112_patches
from .constants import SETTINGS_PREFIX, plane_rectangular_epsg

_APPLIED = False
_CURRENT_SELECTION: set[str] | None = None
_INTERNAL_GROUP = "__gcham_internal__"

LAYER_GROUPS = (
    (
        "施設",
        (
            ("facility_p28", "国・都道府県の機関"),
            ("facility_p05", "市町村役場等及び公的集会施設"),
            ("facility_p04", "医療機関"),
            ("facility_a27", "小学校区"),
            ("facility_p29", "学校"),
        ),
    ),
    (
        "交通",
        (
            ("transport_p11", "バス停留所"),
            ("transport_n07", "バスルート"),
            ("transport_n02_station", "鉄道駅"),
            ("transport_n02_rail", "鉄道路線"),
        ),
    ),
    (
        "道路",
        (("road_n13", "道路（容量大）"),),
    ),
    (
        "災害",
        (
            ("disaster_emergency", "指定緊急避難場所"),
            ("disaster_shelter", "指定避難所"),
            ("disaster_jshis", "J-SHIS 地震ハザード"),
        ),
    ),
    (
        "背景地図",
        (
            ("background_osm", "OpenStreetMap Standard"),
            ("background_photo", "国土地理院 シームレス空中写真"),
            ("background_hillshade", "国土地理院 陰影起伏図"),
        ),
    ),
)

ALL_LAYER_KEYS = {
    key
    for _group_name, children in LAYER_GROUPS
    for key, _label in children
}
DEFAULT_LAYER_KEYS = ALL_LAYER_KEYS - {"road_n13"}
FACILITY_KEYS = {
    "facility_p28": "P28",
    "facility_p05": "P05",
    "facility_p04": "P04",
    "facility_a27": "A27",
    "facility_p29": "P29",
}
TRANSPORT_KEYS = {
    "transport_p11",
    "transport_n07",
    "transport_n02_station",
    "transport_n02_rail",
}
DISASTER_KEYS = {
    "disaster_emergency",
    "disaster_shelter",
    "disaster_jshis",
}
BACKGROUND_KEYS = {
    "background_osm",
    "background_photo",
    "background_hillshade",
}
BACKGROUND_KEY_ORDER = (
    "background_osm",
    "background_photo",
    "background_hillshade",
)


def _qt_item_flag(name: str):
    scope = getattr(Qt, "ItemFlag", Qt)
    return getattr(scope, name)


def _qt_check_state(name: str):
    scope = getattr(Qt, "CheckState", Qt)
    return getattr(scope, name)


def _checked():
    return _qt_check_state("Checked")


def _unchecked():
    return _qt_check_state("Unchecked")


def _partial():
    return _qt_check_state("PartiallyChecked")


def _settings_key(suffix: str) -> str:
    return f"{SETTINGS_PREFIX}/{suffix}"


def _load_layer_selection(dialog) -> set[str]:
    raw = dialog.settings.value(_settings_key("supplemental_layers"), "")
    if raw in (None, ""):
        return set(DEFAULT_LAYER_KEYS)
    try:
        values = set(json.loads(str(raw)))
    except (TypeError, ValueError, json.JSONDecodeError):
        return set(DEFAULT_LAYER_KEYS)
    return values.intersection(ALL_LAYER_KEYS)


def _save_layer_selection(dialog) -> None:
    if not hasattr(dialog, "supplemental_tree"):
        return
    values = sorted(_selected_layer_keys(dialog))
    dialog.settings.setValue(
        _settings_key("supplemental_layers"),
        json.dumps(values, ensure_ascii=False),
    )


def _selected_layer_keys(dialog) -> set[str]:
    result = set()
    tree = dialog.supplemental_tree
    role = dialog_module._user_role()
    for i in range(tree.topLevelItemCount()):
        root = tree.topLevelItem(i)
        for j in range(root.childCount()):
            child = root.child(j)
            key = str(child.data(0, role) or "")
            if key and child.checkState(0) == _checked():
                result.add(key)
    return result


def _set_tree_selection(dialog, selected: set[str]) -> None:
    tree = dialog.supplemental_tree
    role = dialog_module._user_role()
    dialog._supplemental_tree_guard = True
    try:
        for i in range(tree.topLevelItemCount()):
            root = tree.topLevelItem(i)
            states = []
            for j in range(root.childCount()):
                child = root.child(j)
                key = str(child.data(0, role) or "")
                state = _checked() if key in selected else _unchecked()
                child.setCheckState(0, state)
                states.append(state)
            if states and all(state == _checked() for state in states):
                root.setCheckState(0, _checked())
            elif states and all(state == _unchecked() for state in states):
                root.setCheckState(0, _unchecked())
            else:
                root.setCheckState(0, _partial())
    finally:
        dialog._supplemental_tree_guard = False


def _tree_item_changed(dialog, item: QTreeWidgetItem, _column: int) -> None:
    if getattr(dialog, "_supplemental_tree_guard", False):
        return
    dialog._supplemental_tree_guard = True
    try:
        parent = item.parent()
        if parent is None:
            state = item.checkState(0)
            if state in (_checked(), _unchecked()):
                for i in range(item.childCount()):
                    item.child(i).setCheckState(0, state)
        else:
            states = [parent.child(i).checkState(0) for i in range(parent.childCount())]
            if all(state == _checked() for state in states):
                parent.setCheckState(0, _checked())
            elif all(state == _unchecked() for state in states):
                parent.setCheckState(0, _unchecked())
            else:
                parent.setCheckState(0, _partial())
    finally:
        dialog._supplemental_tree_guard = False
    _save_layer_selection(dialog)


def _reset_layer_selection(dialog) -> None:
    _set_tree_selection(dialog, set(DEFAULT_LAYER_KEYS))
    _save_layer_selection(dialog)


def _apply_layer_only_state(dialog) -> None:
    if not hasattr(dialog, "layer_only_check"):
        return
    layer_only = dialog.layer_only_check.isChecked()
    available = not dialog._running
    for widget in (
        dialog.radio_all,
        dialog.radio_selected,
        dialog.preset_check,
        dialog.extra_button,
        dialog.reset_extra_button,
    ):
        widget.setEnabled(available and not layer_only)
    dialog.muni_button.setEnabled(
        available and not layer_only and dialog.radio_selected.isChecked()
    )
    dialog.create_button.setText(
        "選択した追加レイヤを追加" if layer_only else "データパックを作成"
    )


def _patch_dialog_ui() -> None:
    cls = dialog_module.GCHAMDataPackDialog
    original_build_ui = cls._build_ui
    if getattr(original_build_ui, "_gcham_v113_layers", False):
        return

    def _build_ui(self):
        original_build_ui(self)

        # Hide the legacy group-level controls while keeping them available to
        # the existing BuildOptions pathway internally.
        for widget in (
            self.facilities_check,
            self.transport_check,
            self.disaster_check,
            self.background_check,
            self.roads_check,
        ):
            widget.setVisible(False)

        group_widget = self.facilities_check.parentWidget()
        group_layout = group_widget.layout()
        for label in group_widget.findChildren(QLabel):
            if "道路データは容量が大きいため" in label.text():
                label.setVisible(False)

        self.layer_only_check = QCheckBox("既存データパックへ追加レイヤのみ追加")
        self.layer_only_check.setToolTip(
            "ONの場合、e-Stat 6表・250m人口・行政区域FGBを再生成せず、選択した追加レイヤだけを作成します。"
        )
        group_layout.insertWidget(0, self.layer_only_check)

        self.supplemental_tree = QTreeWidget()
        self.supplemental_tree.setColumnCount(1)
        self.supplemental_tree.setHeaderLabel("追加するレイヤ")
        self.supplemental_tree.setMinimumHeight(250)
        self._supplemental_tree_guard = True
        selected = _load_layer_selection(self)
        role = dialog_module._user_role()
        for group_name, children in LAYER_GROUPS:
            root = QTreeWidgetItem([group_name])
            root.setFlags(
                root.flags()
                | _qt_item_flag("ItemIsUserCheckable")
                | _qt_item_flag("ItemIsEnabled")
            )
            self.supplemental_tree.addTopLevelItem(root)
            for key, label in children:
                child = QTreeWidgetItem([label])
                child.setData(0, role, key)
                child.setFlags(
                    child.flags()
                    | _qt_item_flag("ItemIsUserCheckable")
                    | _qt_item_flag("ItemIsEnabled")
                )
                child.setCheckState(0, _checked() if key in selected else _unchecked())
                root.addChild(child)
            root.setExpanded(True)
        self._supplemental_tree_guard = False
        _set_tree_selection(self, selected)
        group_layout.insertWidget(1, self.supplemental_tree)

        button_row = QHBoxLayout()
        self.reset_layers_button = QPushButton("追加レイヤを初期設定に戻す")
        button_row.addStretch(1)
        button_row.addWidget(self.reset_layers_button)
        group_layout.insertLayout(2, button_row)

        self.supplemental_tree.itemChanged.connect(
            lambda item, column: _tree_item_changed(self, item, column)
        )
        self.reset_layers_button.clicked.connect(lambda: _reset_layer_selection(self))
        self.layer_only_check.toggled.connect(lambda _checked_value: _apply_layer_only_state(self))
        _apply_layer_only_state(self)

    _build_ui._gcham_v113_layers = True
    cls._build_ui = _build_ui

    original_set_running = cls._set_running

    def _set_running(self, running):
        original_set_running(self, running)
        if hasattr(self, "supplemental_tree"):
            self.supplemental_tree.setEnabled(not running)
            self.reset_layers_button.setEnabled(not running)
            self.layer_only_check.setEnabled(not running)
            _apply_layer_only_state(self)

    cls._set_running = _set_running


def _patch_facility_selection() -> None:
    original = supplemental.SupplementalBuilder.build_facilities
    if getattr(original, "_gcham_v113_layers", False):
        return

    def build_facilities(self):
        if _CURRENT_SELECTION is None:
            return original(self)
        wanted_datasets = {
            dataset
            for key, dataset in FACILITY_KEYS.items()
            if key in _CURRENT_SELECTION
        }
        if not wanted_datasets:
            return []
        saved_specs = supplemental.FACILITY_SPECS
        supplemental.FACILITY_SPECS = tuple(
            spec for spec in saved_specs if spec[0] in wanted_datasets
        )
        try:
            return original(self)
        finally:
            supplemental.FACILITY_SPECS = saved_specs

    build_facilities._gcham_v113_layers = True
    supplemental.SupplementalBuilder.build_facilities = build_facilities


def _selected_transport_build(self):
    results = []
    wanted = TRANSPORT_KEYS.intersection(_CURRENT_SELECTION or set())
    if not wanted:
        return results

    pref_dataset_keys = {
        "P11": "transport_p11",
        "N07": "transport_n07",
    }
    for dataset, yy, year, filename_tpl, title, out_tpl, style in supplemental.TRANSPORT_PREF_SPECS:
        if pref_dataset_keys.get(dataset) not in wanted:
            continue
        self.check_cancelled()
        filename = filename_tpl.format(pref=self.pref_code)
        vectors = self._ksj_vectors(dataset, yy, filename)
        out = self.data_dir / out_tpl.format(pref=self.pref_code)
        qgis_io.remove_existing_layer_for_path(out)
        out.unlink(missing_ok=True)
        supplemental._write_merged_vectors(vectors, out, self.target_epsg)
        results.append(
            supplemental.SupplementalResult(
                out,
                f"{title}_{year}_国土数値情報",
                "交通",
                style,
            )
        )

    need_station = "transport_n02_station" in wanted
    need_rail = "transport_n02_rail" in wanted
    if not (need_station or need_rail):
        return results

    self.log("N02-2025全国鉄道データを都道府県範囲で事前抽出します。")
    n02 = self._ksj_vectors("N02", "25", "N02-25_GML.zip")
    station_sources = [p for p in n02 if "station" in p.stem.lower()]
    rail_sources = [
        p
        for p in n02
        if "railroadsection" in p.stem.lower()
        or ("railroad" in p.stem.lower() and "station" not in p.stem.lower())
    ]
    if not station_sources or not rail_sources:
        cache = self.cache / "ksj" / "N02" / "N02-25_GML"
        all_vectors = supplemental._source_vector_files(cache)
        station_sources = [p for p in all_vectors if "station" in p.stem.lower()]
        rail_sources = [
            p
            for p in all_vectors
            if "railroadsection" in p.stem.lower()
            or ("railroad" in p.stem.lower() and "station" not in p.stem.lower())
        ]
    if need_station and not station_sources:
        raise RuntimeError("N02-2025からStationを識別できませんでした。")
    if need_rail and not rail_sources:
        raise RuntimeError("N02-2025からRailroadSectionを識別できませんでした。")

    if need_station:
        station_out = self.data_dir / f"n02_2025_{self.pref_code}_stations.fgb"
        qgis_io.remove_existing_layer_for_path(station_out)
        station_out.unlink(missing_ok=True)
        v112_patches._write_n02_prefecture_filtered(
            station_sources,
            station_out,
            self.target_epsg,
            self.pref_geometry,
            self.log,
            self.check_cancelled,
            "鉄道駅",
        )
        results.append(
            supplemental.SupplementalResult(
                station_out,
                "鉄道駅_2025_国土数値情報",
                "交通",
                "rail_station",
            )
        )

    if need_rail:
        rail_out = self.data_dir / f"n02_2025_{self.pref_code}_railway_lines.fgb"
        qgis_io.remove_existing_layer_for_path(rail_out)
        rail_out.unlink(missing_ok=True)
        v112_patches._write_n02_prefecture_filtered(
            rail_sources,
            rail_out,
            self.target_epsg,
            self.pref_geometry,
            self.log,
            self.check_cancelled,
            "鉄道路線",
        )
        results.append(
            supplemental.SupplementalResult(
                rail_out,
                "鉄道路線_2025_国土数値情報",
                "交通",
                "rail_line",
            )
        )
    return results


def _patch_transport_selection() -> None:
    original = supplemental.SupplementalBuilder.build_transport
    if getattr(original, "_gcham_v113_layers", False):
        return

    def build_transport(self):
        if _CURRENT_SELECTION is None:
            return original(self)
        return _selected_transport_build(self)

    build_transport._gcham_v113_layers = True
    supplemental.SupplementalBuilder.build_transport = build_transport


def _selected_gsi_disaster(self, wanted: set[str]):
    results = []
    need_emergency = "disaster_emergency" in wanted
    need_shelter = "disaster_shelter" in wanted
    if not (need_emergency or need_shelter):
        return results

    try:
        gsi_date, emergency_url, shelter_url = self._gsi_info()
        gsi_cache = self.cache / "gsi" / self.pref_code
        if need_emergency:
            emergency_csv = gsi_cache / f"emergency_{gsi_date}.csv"
            if not (self.reuse and emergency_csv.exists()):
                supplemental.download_file(emergency_url, emergency_csv, log=self.log)
            emergency_out = self.data_dir / f"gsi_emergency_evacuation_{gsi_date}_{self.pref_code}.fgb"
            qgis_io.remove_existing_layer_for_path(emergency_out)
            emergency_out.unlink(missing_ok=True)
            self._gsi_csv_to_fgb(emergency_csv, emergency_out)
            results.append(
                supplemental.SupplementalResult(
                    emergency_out,
                    f"指定緊急避難場所_{gsi_date}_国土地理院",
                    "災害",
                    "gsi_emergency",
                )
            )
        if need_shelter:
            shelter_csv = gsi_cache / f"shelter_{gsi_date}.csv"
            if not (self.reuse and shelter_csv.exists()):
                supplemental.download_file(shelter_url, shelter_csv, log=self.log)
            shelter_out = self.data_dir / f"gsi_designated_shelter_{gsi_date}_{self.pref_code}.fgb"
            qgis_io.remove_existing_layer_for_path(shelter_out)
            shelter_out.unlink(missing_ok=True)
            self._gsi_csv_to_fgb(shelter_csv, shelter_out)
            results.append(
                supplemental.SupplementalResult(
                    shelter_out,
                    f"指定避難所_{gsi_date}_国土地理院",
                    "災害",
                    "gsi_shelter",
                )
            )
    except Exception as exc:
        gsi_date = date.today().strftime("%Y%m%d")
        self.log(
            "GSI都道府県別CSVを公開ページから解決できなかったため、公式GeoJSONタイルへフォールバックします。"
            f" レイヤ日付は取得日 {gsi_date} を使用します。詳細: {exc}"
        )
        if need_emergency:
            emergency_out = self.data_dir / f"gsi_emergency_evacuation_{gsi_date}_{self.pref_code}.fgb"
            qgis_io.remove_existing_layer_for_path(emergency_out)
            emergency_out.unlink(missing_ok=True)
            records = self._gsi_tile_records(
                [f"skhb{i:02d}" for i in range(1, 9)],
                True,
            )
            self._gsi_tile_records_to_fgb(records, emergency_out, True)
            results.append(
                supplemental.SupplementalResult(
                    emergency_out,
                    f"指定緊急避難場所_{gsi_date}_国土地理院",
                    "災害",
                    "gsi_emergency",
                )
            )
        if need_shelter:
            shelter_out = self.data_dir / f"gsi_designated_shelter_{gsi_date}_{self.pref_code}.fgb"
            qgis_io.remove_existing_layer_for_path(shelter_out)
            shelter_out.unlink(missing_ok=True)
            records = self._gsi_tile_records(["sih", "sfh"], False)
            self._gsi_tile_records_to_fgb(records, shelter_out, False)
            results.append(
                supplemental.SupplementalResult(
                    shelter_out,
                    f"指定避難所_{gsi_date}_国土地理院",
                    "災害",
                    "gsi_shelter",
                )
            )
    return results


def _selected_jshis(self):
    results = []
    j_vectors, missing = self._jshis_first_mesh_vectors()
    if missing:
        cache = self.cache / "jshis" / "Y2024_MAX"
        self.log(
            "J-SHIS 1次メッシュの自動取得が完了しなかったため、WMSへフォールバックします。"
            "不足メッシュ: "
            + ", ".join(missing)
            + f"。公式ZIPを手動取得した場合は {cache} に置くと次回再利用します。"
        )
    if j_vectors and not missing:
        j_out = self.data_dir / f"jshis_pshm_t30_p03_si_2024_{self.pref_code}.fgb"
        qgis_io.remove_existing_layer_for_path(j_out)
        j_out.unlink(missing_ok=True)
        supplemental._write_merged_vectors(
            j_vectors,
            j_out,
            self.target_epsg,
            self.pref_geometry,
            clip_to_pref=True,
        )
        check = QgsVectorLayer(str(j_out), "jshis_output_check", "ogr")
        if not check.isValid() or check.fields().indexOf("T30_P03_SI") < 0:
            j_out.unlink(missing_ok=True)
            raise RuntimeError("J-SHIS出力FGBにT30_P03_SIを確認できませんでした。")
        results.append(
            supplemental.SupplementalResult(
                j_out,
                "確率論的地震動予測地図（30年超過確率3%・計測震度）_2024_J-SHIS",
                "災害",
                "jshis",
            )
        )
    return results


def _patch_disaster_selection() -> None:
    original = supplemental.SupplementalBuilder.build_disaster
    original_add_results = supplemental.SupplementalBuilder.add_results
    if getattr(original, "_gcham_v113_layers", False):
        return

    def build_disaster(self):
        if _CURRENT_SELECTION is None:
            return original(self)
        wanted = DISASTER_KEYS.intersection(_CURRENT_SELECTION)
        if not wanted:
            return []
        results = _selected_gsi_disaster(self, wanted)
        if "disaster_jshis" in wanted:
            results.extend(_selected_jshis(self))
        else:
            # Suppress the legacy processor's automatic J-SHIS fallback when the
            # user intentionally did not select J-SHIS.
            results.append(
                supplemental.SupplementalResult(
                    Path("."),
                    "",
                    _INTERNAL_GROUP,
                    "jshis",
                )
            )
        return results

    def add_results(self, results):
        visible_results = [r for r in results if r.group != _INTERNAL_GROUP]
        return original_add_results(self, visible_results)

    build_disaster._gcham_v113_layers = True
    supplemental.SupplementalBuilder.build_disaster = build_disaster
    supplemental.SupplementalBuilder.add_results = add_results


def _add_selected_background_group() -> None:
    if _CURRENT_SELECTION is None:
        return _ORIGINAL_ADD_BACKGROUND()
    selected_keys = BACKGROUND_KEYS.intersection(_CURRENT_SELECTION)
    if not selected_keys:
        return None
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup("背景地図") or root.addGroup("背景地図")
    insert_index = 0
    for key, spec in zip(BACKGROUND_KEY_ORDER, supplemental.BACKGROUND_TILES):
        if key not in selected_keys:
            continue
        name, url, zmin, zmax, visible, opacity = spec
        for old_layer in list(project.mapLayersByName(name)):
            project.removeMapLayer(old_layer.id())
        uri = f"type=xyz&url={url}&zmin={zmin}&zmax={zmax}"
        layer = QgsRasterLayer(uri, name, "wms")
        if not layer.isValid():
            raise RuntimeError(f"XYZタイルを追加できません: {name}")
        renderer = layer.renderer()
        if renderer is not None and hasattr(renderer, "setOpacity"):
            renderer.setOpacity(opacity)
        project.addMapLayer(layer, False)
        node = group.insertLayer(insert_index, layer)
        node.setItemVisibilityChecked(visible)
        insert_index += 1
    group.setItemVisibilityChecked(True)
    return None


_ORIGINAL_ADD_BACKGROUND = supplemental.add_background_group


def _patch_background_selection() -> None:
    supplemental.add_background_group = _add_selected_background_group
    processor_module.add_background_group = _add_selected_background_group


def _selection_has(prefix_set: set[str]) -> bool:
    return bool((_CURRENT_SELECTION or set()).intersection(prefix_set))


def _build_supplemental_only(processor, output: Path, pref_code: str, pref_name: str, reuse: bool):
    processor.progress(2, "行政区域を準備しています")
    n03_vector = processor.ensure_n03(pref_code, output, reuse)
    municipalities, _n03_fields = qgis_io.load_and_dissolve_n03(n03_vector)
    target_epsg = plane_rectangular_epsg(pref_code)
    processor.log(f"追加レイヤのみモード / 出力CRS: EPSG:{target_epsg}")

    builder = supplemental.SupplementalBuilder(
        output,
        pref_code,
        pref_name,
        target_epsg,
        municipalities,
        reuse=reuse,
        log=processor.log,
        is_cancelled=processor.is_cancelled_cb,
    )
    results = []
    if _selection_has(set(FACILITY_KEYS)):
        processor.progress(15, "選択した施設レイヤを作成しています")
        results.extend(builder.safe_build("build_facilities"))
    if _selection_has(TRANSPORT_KEYS):
        processor.progress(35, "選択した交通レイヤを作成しています")
        results.extend(builder.safe_build("build_transport"))
    if "road_n13" in (_CURRENT_SELECTION or set()):
        processor.progress(55, "道路データを作成しています")
        results.extend(builder.safe_build("build_roads"))
    if _selection_has(DISASTER_KEYS):
        processor.progress(72, "選択した災害レイヤを作成しています")
        results.extend(builder.safe_build("build_disaster"))

    processor.progress(92, "QGISへ選択レイヤを追加しています")
    builder.add_results(results)
    if "disaster_jshis" in (_CURRENT_SELECTION or set()) and not any(
        r.style == "jshis" and r.group != _INTERNAL_GROUP for r in results
    ):
        fallback = supplemental.add_jshis_wms_fallback(builder.pref_geometry)
        processor.log(
            "J-SHISはFGBを生成できなかったためWMS代替を使用しました。"
            "不透明度70%。表示は選択都道府県のN03行政区域に制限します。"
        )
        if fallback.customProperty("gcham/jshis_canvas_clip_applied", False):
            processor.log("J-SHIS WMS: 都道府県N03による描画クリップを適用しました。")

    if _selection_has(BACKGROUND_KEYS):
        _add_selected_background_group()

    processor.progress(100, "選択した追加レイヤの作成が完了しました")
    return [r for r in results if r.group != _INTERNAL_GROUP]


def _patch_run_build() -> None:
    cls = dialog_module.GCHAMDataPackDialog
    original_run = cls._run_build
    if getattr(original_run, "_gcham_v113_layers", False):
        return

    def _run_build(self):
        global _CURRENT_SELECTION
        selection = _selected_layer_keys(self)
        _save_layer_selection(self)
        if self.layer_only_check.isChecked() and not selection:
            QMessageBox.warning(
                self,
                "追加レイヤが未選択です",
                "追加するレイヤを1つ以上選択してください。",
            )
            return

        _CURRENT_SELECTION = set(selection)
        try:
            # Keep the original group-level BuildOptions pathway for a complete
            # data-pack run, but drive it from the child-level tree selection.
            self.facilities_check.setChecked(_selection_has(set(FACILITY_KEYS)))
            self.transport_check.setChecked(_selection_has(TRANSPORT_KEYS))
            self.roads_check.setChecked("road_n13" in selection)
            self.disaster_check.setChecked(_selection_has(DISASTER_KEYS))
            self.background_check.setChecked(_selection_has(BACKGROUND_KEYS))

            if not self.layer_only_check.isChecked():
                return original_run(self)

            output = self._ensure_output_dir()
            if output is None:
                return None
            code, name = self._pref_data()
            self._cancelled = False
            self.log_box.clear()
            self._set_running(True)
            try:
                results = _build_supplemental_only(
                    self._processor(),
                    output,
                    code,
                    name,
                    self.reuse_check.isChecked(),
                )
                QMessageBox.information(
                    self,
                    "完了",
                    "選択した追加レイヤを作成しました。\n\n"
                    f"出力先: {output}\n追加レイヤ数: {len(results)}",
                )
            except qgis_io.CancelledError as exc:
                self._log(str(exc))
                self._set_progress(self.progress_bar.value(), "処理を中止しました")
            except Exception as exc:
                self._log(f"ERROR: {exc}")
                QMessageBox.critical(self, "G-CHAM Data Pack Builder", str(exc))
                self._set_progress(self.progress_bar.value(), "エラーで停止しました")
            finally:
                self._set_running(False)
            return None
        finally:
            _CURRENT_SELECTION = None

    _run_build._gcham_v113_layers = True
    cls._run_build = _run_build


def apply_v113_layer_selection() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_facility_selection()
    _patch_transport_selection()
    _patch_disaster_selection()
    _patch_background_selection()
    _patch_dialog_ui()
    _patch_run_build()
    _APPLIED = True
