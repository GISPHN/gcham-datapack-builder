# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import gc
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsFeature, QgsFeatureRequest, QgsGeometry, QgsVectorLayer, QgsWkbTypes

from . import dialog as dialog_module
from . import qgis_io
from . import supplemental
from . import v112_patches
from . import v113_layer_selection
from .constants import plane_rectangular_epsg

_APPLIED = False
_ACTIVE_ALL_MUNICIPALITIES = True
_ACTIVE_MUNICIPALITY_CODES: set[str] = set()


def _point_geometry_type():
    value = getattr(QgsWkbTypes, "PointGeometry", None)
    if value is not None:
        return value
    scope = getattr(QgsWkbTypes, "GeometryType", QgsWkbTypes)
    return getattr(scope, "Point")


def _apply_layer_only_state(dialog) -> None:
    """Keep municipality controls usable while population controls are disabled."""
    if not hasattr(dialog, "layer_only_check"):
        return
    layer_only = dialog.layer_only_check.isChecked()
    available = not dialog._running

    dialog.radio_all.setEnabled(available)
    dialog.radio_selected.setEnabled(available)
    for widget in (
        dialog.preset_check,
        dialog.extra_button,
        dialog.reset_extra_button,
    ):
        widget.setEnabled(available and not layer_only)

    dialog.muni_button.setEnabled(available and dialog.radio_selected.isChecked())
    dialog.create_button.setText(
        "選択した追加レイヤを追加" if layer_only else "データパックを作成"
    )


def _scope_municipalities(all_municipalities):
    if _ACTIVE_ALL_MUNICIPALITIES:
        return list(all_municipalities)
    selected = [
        muni for muni in all_municipalities
        if muni.code in _ACTIVE_MUNICIPALITY_CODES
    ]
    missing = sorted(
        _ACTIVE_MUNICIPALITY_CODES - {muni.code for muni in selected}
    )
    if missing:
        raise RuntimeError(
            "選択した自治体コードをN03で確認できません: " + ", ".join(missing)
        )
    if not selected:
        raise RuntimeError("追加レイヤの対象自治体が選択されていません。")
    return selected


def _scope_geometry(municipalities) -> QgsGeometry:
    geometry = QgsGeometry.unaryUnion(
        [QgsGeometry(muni.geometry) for muni in municipalities]
    )
    if geometry.isNull() or geometry.isEmpty():
        raise RuntimeError("選択自治体の行政区域を作成できませんでした。")
    return geometry


def _write_p04_scoped(
    sources: list[Path],
    out_path: Path,
    target_epsg: int,
    log,
    check_cancelled,
    scope_geometry: QgsGeometry,
    encoding: str | None = None,
):
    if not sources:
        raise RuntimeError("P04医療機関の入力ベクタがありません。")
    first = v112_patches._open_source_layer(sources[0], "p04_source", encoding)
    base_names = [field.name() for field in first.fields()]
    out_fields = supplemental._copy_fields(first.fields())
    writer = supplemental._create_writer(
        out_path, out_fields, first.wkbType(), target_epsg
    )
    prepared_scope, engine = v112_patches._prepared_prefecture_geometry(scope_geometry)
    written = 0
    sample_name = None
    try:
        for source_path in sources:
            check_cancelled()
            layer = v112_patches._open_source_layer(
                source_path, "p04_source", encoding
            )
            to_target = supplemental._transform(layer.crs(), target_epsg)
            to_geo = supplemental._geo_transform(layer.crs())
            request = QgsFeatureRequest()
            try:
                request.setFilterRect(
                    v112_patches._source_filter_rect(prepared_scope, layer.crs())
                )
            except Exception as exc:
                log(f"P04医療機関: bbox事前抽出を適用できません: {exc}")
            field_names = [field.name() for field in layer.fields()]
            for source_feature in layer.getFeatures(request):
                if (
                    not source_feature.hasGeometry()
                    or source_feature.geometry().isEmpty()
                ):
                    continue
                check_geometry = supplemental._copy_geom(
                    source_feature.geometry(), to_geo
                )
                if not v112_patches._intersects_prefecture(
                    engine, prepared_scope, check_geometry
                ):
                    continue
                feature = QgsFeature(out_fields)
                feature.setGeometry(
                    supplemental._copy_geom(
                        source_feature.geometry(), to_target
                    )
                )
                feature.setAttributes(
                    [
                        source_feature[name] if name in field_names else None
                        for name in base_names
                    ]
                )
                if not writer.addFeature(feature):
                    raise RuntimeError(
                        f"FGB書き込みに失敗しました: {out_path}"
                    )
                if sample_name is None and "P04_002" in field_names:
                    value = source_feature["P04_002"]
                    if value not in (None, ""):
                        sample_name = str(value)
                written += 1
                if written % 500 == 0:
                    QCoreApplication.processEvents()
                    check_cancelled()
    finally:
        del writer
        gc.collect()

    if written == 0:
        raise RuntimeError(f"対象地物が0件でした: {out_path.name}")
    source_kind = (
        "GML優先"
        if all(path.suffix.lower() == ".gml" for path in sources)
        else "Shapefile CP932"
    )
    log(f"P04医療機関: 選択自治体内 {written:,}件 / {source_kind}")
    if sample_name:
        log(f"P04文字列確認 P04_002: {sample_name}")
    return out_path


def _municipality_result_path(path: Path, pref_code: str, muni_code: str) -> Path:
    """Return a municipality-coded filename without changing source download keys."""
    name = path.name
    middle = f"_{pref_code}_"
    if middle in name:
        name = name.replace(middle, f"_{muni_code}_", 1)
    elif name.endswith(f"_{pref_code}.fgb"):
        name = name[: -len(f"_{pref_code}.fgb")] + f"_{muni_code}.fgb"
    else:
        name = f"{path.stem}_{muni_code}{path.suffix}"
    return path.with_name(name)


def _rename_result_for_municipality(result, pref_code: str, municipality):
    source = Path(result.path)
    target = _municipality_result_path(source, pref_code, municipality.code)
    if source.exists() and source != target:
        qgis_io.remove_existing_layer_for_path(target)
        target.unlink(missing_ok=True)
        source.replace(target)
    return supplemental.SupplementalResult(
        target,
        f"{municipality.name}_{result.display_name}",
        result.group,
        result.style,
    )


def _run_builder_for_scope(processor, builder, scope_geometry, pref_code, municipality):
    """Run selected supplemental builders for one municipality and rename outputs safely."""
    original_write = supplemental._write_merged_vectors
    original_p04 = v112_patches._write_p04_vectors

    def scoped_write(
        sources,
        out_path,
        target_epsg,
        pref_geometry=None,
        extra_maps=None,
        clip_to_pref=False,
    ):
        if pref_geometry is None:
            pref_geometry = scope_geometry
            first = QgsVectorLayer(str(sources[0]), "scope_type", "ogr")
            if first.isValid():
                geometry_type = QgsWkbTypes.geometryType(first.wkbType())
                clip_to_pref = geometry_type != _point_geometry_type()
        return original_write(
            sources,
            out_path,
            target_epsg,
            pref_geometry,
            extra_maps,
            clip_to_pref,
        )

    def scoped_p04(
        sources,
        out_path,
        target_epsg,
        log,
        check_cancelled,
        encoding=None,
    ):
        return _write_p04_scoped(
            sources,
            out_path,
            target_epsg,
            log,
            check_cancelled,
            scope_geometry,
            encoding,
        )

    supplemental._write_merged_vectors = scoped_write
    v112_patches._write_p04_vectors = scoped_p04
    raw_results = []
    try:
        if v113_layer_selection._selection_has(
            set(v113_layer_selection.FACILITY_KEYS)
        ):
            raw_results.extend(builder.safe_build("build_facilities"))
        if v113_layer_selection._selection_has(
            v113_layer_selection.TRANSPORT_KEYS
        ):
            raw_results.extend(builder.safe_build("build_transport"))
        if "road_n13" in (v113_layer_selection._CURRENT_SELECTION or set()):
            raw_results.extend(builder.safe_build("build_roads"))
        if v113_layer_selection._selection_has(
            v113_layer_selection.DISASTER_KEYS
        ):
            raw_results.extend(builder.safe_build("build_disaster"))
    finally:
        supplemental._write_merged_vectors = original_write
        v112_patches._write_p04_vectors = original_p04

    renamed = [
        _rename_result_for_municipality(result, pref_code, municipality)
        for result in raw_results
    ]
    builder.add_results(renamed)
    processor.log(
        f"追加レイヤ作成完了: {municipality.code} {municipality.name} / "
        f"{len([r for r in renamed if r.group != v113_layer_selection._INTERNAL_GROUP])}レイヤ"
    )
    return renamed


def _patch_supplemental_only_scope() -> None:
    original_build = v113_layer_selection._build_supplemental_only

    def build_supplemental_only(
        processor,
        output: Path,
        pref_code: str,
        pref_name: str,
        reuse: bool,
    ):
        if _ACTIVE_ALL_MUNICIPALITIES:
            return original_build(processor, output, pref_code, pref_name, reuse)

        processor.progress(2, "行政区域を準備しています")
        n03_vector = processor.ensure_n03(pref_code, output, reuse)
        all_municipalities, _fields = qgis_io.load_and_dissolve_n03(n03_vector)
        municipalities = _scope_municipalities(all_municipalities)
        target_epsg = plane_rectangular_epsg(pref_code)
        names = ", ".join(
            f"{muni.code} {muni.name}" for muni in municipalities
        )
        processor.log(
            f"追加レイヤのみモード / 選択自治体 {len(municipalities)}件 / "
            f"出力CRS: EPSG:{target_epsg}"
        )
        processor.log(f"追加レイヤ対象自治体: {names}")

        all_results = []
        visible_jshis = False
        for index, municipality in enumerate(municipalities, start=1):
            processor.check_cancelled()
            processor.progress(
                min(90, 5 + int(80 * (index - 1) / max(1, len(municipalities)))),
                f"追加レイヤ作成: {municipality.name} ({index}/{len(municipalities)})",
            )
            builder = supplemental.SupplementalBuilder(
                output,
                pref_code,
                pref_name,
                target_epsg,
                [municipality],
                reuse=reuse,
                log=processor.log,
                is_cancelled=processor.is_cancelled_cb,
            )
            scoped_results = _run_builder_for_scope(
                processor,
                builder,
                _scope_geometry([municipality]),
                pref_code,
                municipality,
            )
            all_results.extend(scoped_results)
            if any(
                result.style == "jshis"
                and result.group != v113_layer_selection._INTERNAL_GROUP
                for result in scoped_results
            ):
                visible_jshis = True

        if (
            "disaster_jshis" in (v113_layer_selection._CURRENT_SELECTION or set())
            and not visible_jshis
        ):
            combined_scope = _scope_geometry(municipalities)
            supplemental.add_jshis_wms_fallback(combined_scope)
            processor.log(
                "J-SHISはFGBを生成できなかったため、選択自治体範囲を結合したWMS代替を使用しました。"
            )

        if v113_layer_selection._selection_has(
            v113_layer_selection.BACKGROUND_KEYS
        ):
            v113_layer_selection._add_selected_background_group()

        processor.progress(100, "選択した追加レイヤの作成が完了しました")
        return [
            result for result in all_results
            if result.group != v113_layer_selection._INTERNAL_GROUP
        ]

    v113_layer_selection._build_supplemental_only = build_supplemental_only


def _patch_run_scope() -> None:
    cls = dialog_module.GCHAMDataPackDialog
    original_run = cls._run_build
    if getattr(original_run, "_gcham_v113_municipality_scope", False):
        return

    def _run_build(self):
        global _ACTIVE_ALL_MUNICIPALITIES, _ACTIVE_MUNICIPALITY_CODES
        layer_only = (
            hasattr(self, "layer_only_check")
            and self.layer_only_check.isChecked()
        )
        if layer_only and self.radio_selected.isChecked():
            if not self._selected_muni_codes:
                self._choose_municipalities()
            if not self._selected_muni_codes:
                return None

        _ACTIVE_ALL_MUNICIPALITIES = self.radio_all.isChecked()
        _ACTIVE_MUNICIPALITY_CODES = set(self._selected_muni_codes)
        try:
            return original_run(self)
        finally:
            # Reset only transient processing scope.  The dialog's selected
            # municipality codes and output folder intentionally remain intact
            # so the user can add another layer after a successful run.
            _ACTIVE_ALL_MUNICIPALITIES = True
            _ACTIVE_MUNICIPALITY_CODES = set()

    _run_build._gcham_v113_municipality_scope = True
    cls._run_build = _run_build


def apply_v113_municipality_scope() -> None:
    global _APPLIED
    if _APPLIED:
        return
    v113_layer_selection._apply_layer_only_state = _apply_layer_only_state
    _patch_supplemental_only_scope()
    _patch_run_scope()
    _APPLIED = True
