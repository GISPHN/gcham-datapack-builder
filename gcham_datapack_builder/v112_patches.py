# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import gc
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QElapsedTimer, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QLabel
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsFillSymbol,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
)

from . import dialog as dialog_module
from . import processor as processor_module
from . import qgis_io
from . import supplemental
from .constants import GEOGRAPHIC_CRS_EPSG, plane_rectangular_epsg

_APPLIED = False


def _write_prefecture_admin(path: Path, pref_code: str, pref_name: str, municipalities, target_epsg: int):
    geometry = QgsGeometry.unaryUnion([QgsGeometry(m.geometry) for m in municipalities])
    if geometry.isNull() or geometry.isEmpty():
        raise RuntimeError("都道府県行政区域を作成できませんでした。")
    if not geometry.isMultipart():
        geometry.convertToMultiType()

    fields = QgsFields()
    fields.append(QgsField("PREF_CODE", qgis_io.qmeta_string()))
    fields.append(QgsField("PREF_NAME", qgis_io.qmeta_string()))

    qgis_io.remove_existing_layer_for_path(path)
    path.unlink(missing_ok=True)
    writer = qgis_io.create_fgb_writer(path, fields, target_epsg)
    feature = QgsFeature(fields)
    feature.setGeometry(
        qgis_io.transform_geometry(geometry, qgis_io.geometry_transformer(target_epsg))
    )
    feature.setAttributes([str(pref_code).zfill(2), pref_name])
    try:
        if not writer.addFeature(feature):
            raise RuntimeError(f"都道府県行政区域FGBへの書き込みに失敗しました: {path}")
        if hasattr(writer, "flushBuffer"):
            writer.flushBuffer()
    finally:
        del writer
        gc.collect()


def _style_prefecture_admin(layer: QgsVectorLayer):
    symbol = QgsFillSymbol.createSimple(
        {
            "color": "255,255,255,0",
            "outline_color": "0,0,0,255",
            "outline_width": "0.96",
            "outline_style": "solid",
        }
    )
    symbol.setOpacity(0.70)
    symbol_layer = symbol.symbolLayer(0)
    if symbol_layer is not None:
        symbol_layer.setStrokeWidth(0.96)
        unit_scope = getattr(Qgis, "RenderUnit", Qgis)
        symbol_layer.setStrokeWidthUnit(getattr(unit_scope, "Millimeters"))
    layer.renderer().setSymbol(symbol)
    layer.triggerRepaint()


def _add_prefecture_admin_layer(path: Path, display_name: str):
    qgis_io.remove_existing_layer_for_path(path)
    layer = QgsVectorLayer(str(path), display_name, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"都道府県行政区域FGBをQGISへ追加できません: {path}")
    _style_prefecture_admin(layer)
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup("行政区域") or root.addGroup("行政区域")
    project.addMapLayer(layer, False)
    group.insertLayer(0, layer)
    return layer


def _patch_processor_build():
    original = processor_module.DataPackProcessor.build
    if getattr(original, "_gcham_v112", False):
        return

    def build(self, options, confirm_existing=None):
        result = original(self, options, confirm_existing)
        n03_vector = self.ensure_n03(
            options.pref_code, options.output_dir, options.reuse_downloads
        )
        all_municipalities, _fields = qgis_io.load_and_dissolve_n03(n03_vector)
        pref_admin = (
            options.output_dir
            / "admin"
            / f"n03_{str(options.pref_code).zfill(2)}_pref_admin.fgb"
        )
        target_epsg = plane_rectangular_epsg(options.pref_code)
        _write_prefecture_admin(
            pref_admin,
            options.pref_code,
            options.pref_name,
            all_municipalities,
            target_epsg,
        )
        _add_prefecture_admin_layer(
            pref_admin,
            f"{options.pref_name}_行政区域_国土数値情報",
        )
        self.log(
            f"都道府県行政区域を追加: {options.pref_name} / {pref_admin.name}"
        )
        result["pref_admin"] = pref_admin
        return result

    build._gcham_v112 = True
    processor_module.DataPackProcessor.build = build


def _open_source_layer(path: Path, name: str, encoding: str | None = None) -> QgsVectorLayer:
    layer = QgsVectorLayer(str(path), name, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"入力データを開けません: {path}")
    if encoding and path.suffix.lower() == ".shp" and hasattr(layer, "setProviderEncoding"):
        layer.setProviderEncoding(encoding)
    return layer


def _write_p04_vectors(
    sources: list[Path],
    out_path: Path,
    target_epsg: int,
    log,
    check_cancelled,
    encoding: str | None = None,
):
    if not sources:
        raise RuntimeError("P04医療機関の入力ベクタがありません。")
    first = _open_source_layer(sources[0], "p04_source", encoding)
    base_names = [f.name() for f in first.fields()]
    out_fields = supplemental._copy_fields(first.fields())
    writer = supplemental._create_writer(
        out_path, out_fields, first.wkbType(), target_epsg
    )
    written = 0
    sample_name = None
    try:
        for source_path in sources:
            check_cancelled()
            layer = _open_source_layer(source_path, "p04_source", encoding)
            to_target = supplemental._transform(layer.crs(), target_epsg)
            field_names = [f.name() for f in layer.fields()]
            for source_feature in layer.getFeatures():
                if not source_feature.hasGeometry() or source_feature.geometry().isEmpty():
                    continue
                feature = QgsFeature(out_fields)
                feature.setGeometry(
                    supplemental._copy_geom(source_feature.geometry(), to_target)
                )
                attrs = [
                    source_feature[name] if name in field_names else None
                    for name in base_names
                ]
                feature.setAttributes(attrs)
                if not writer.addFeature(feature):
                    raise RuntimeError(f"FGB書き込みに失敗しました: {out_path}")
                if sample_name is None and "P04_002" in field_names:
                    value = source_feature["P04_002"]
                    if value not in (None, ""):
                        sample_name = str(value)
                written += 1
                if written % 1000 == 0:
                    QCoreApplication.processEvents()
                    check_cancelled()
    finally:
        del writer
        gc.collect()
    if written == 0:
        raise RuntimeError(f"対象地物が0件でした: {out_path.name}")
    source_kind = "GML優先" if all(p.suffix.lower() == ".gml" for p in sources) else "Shapefile CP932"
    log(f"P04医療機関: {source_kind} / {written:,}件")
    if sample_name:
        log(f"P04文字列確認 P04_002: {sample_name}")
    return out_path


def _patch_facilities():
    original = supplemental.SupplementalBuilder.build_facilities
    if getattr(original, "_gcham_v112", False):
        return

    def build_facilities(self):
        results = []
        for dataset, yy, year, filename_tpl, title, out_tpl, style in supplemental.FACILITY_SPECS:
            self.check_cancelled()
            filename = filename_tpl.format(pref=self.pref_code)
            vectors = self._ksj_vectors(dataset, yy, filename)
            encoding = None
            if dataset == "P04":
                extract = self.cache / "ksj" / dataset / Path(filename).stem
                gml_vectors = sorted(extract.rglob("*.gml"))
                if gml_vectors:
                    vectors = gml_vectors
                    self.log("P04医療機関: 日本語文字化け回避のためGMLを優先します。")
                else:
                    encoding = "CP932"
                    self.log("P04医療機関: ShapefileをCP932として読み込みます。")
            out = self.data_dir / out_tpl.format(pref=self.pref_code)
            qgis_io.remove_existing_layer_for_path(out)
            out.unlink(missing_ok=True)
            if dataset == "P04":
                _write_p04_vectors(
                    vectors,
                    out,
                    self.target_epsg,
                    self.log,
                    self.check_cancelled,
                    encoding,
                )
            else:
                supplemental._write_merged_vectors(vectors, out, self.target_epsg)
            results.append(
                supplemental.SupplementalResult(
                    out,
                    f"{title}_{year}_国土数値情報",
                    "施設",
                    style,
                )
            )
        return results

    build_facilities._gcham_v112 = True
    supplemental.SupplementalBuilder.build_facilities = build_facilities


def _prepared_prefecture_geometry(pref_geometry: QgsGeometry):
    geometry = QgsGeometry(pref_geometry)
    try:
        if not geometry.isGeosValid():
            geometry = geometry.makeValid()
    except Exception:
        pass
    engine = None
    try:
        engine = QgsGeometry.createGeometryEngine(geometry.constGet())
        if engine is not None:
            engine.prepareGeometry()
    except Exception:
        engine = None
    return geometry, engine


def _intersects_prefecture(engine, pref_geometry: QgsGeometry, feature_geometry: QgsGeometry) -> bool:
    if engine is not None:
        try:
            return bool(engine.intersects(feature_geometry.constGet()))
        except Exception:
            pass
    return bool(feature_geometry.intersects(pref_geometry))


def _source_filter_rect(pref_geometry: QgsGeometry, source_crs: QgsCoordinateReferenceSystem):
    rectangle = pref_geometry.boundingBox()
    geographic = QgsCoordinateReferenceSystem.fromEpsgId(GEOGRAPHIC_CRS_EPSG)
    if source_crs.isValid() and source_crs != geographic:
        transform = QgsCoordinateTransform(
            geographic, source_crs, QgsProject.instance().transformContext()
        )
        rectangle = transform.transformBoundingBox(rectangle)
    return rectangle


def _write_n02_prefecture_filtered(
    sources: list[Path],
    out_path: Path,
    target_epsg: int,
    pref_geometry: QgsGeometry,
    log,
    check_cancelled,
    label: str,
):
    if not sources:
        raise RuntimeError(f"N02 {label} の入力ベクタがありません。")
    first = _open_source_layer(sources[0], f"n02_{label}")
    base_names = [f.name() for f in first.fields()]
    out_fields = supplemental._copy_fields(first.fields())
    writer = supplemental._create_writer(
        out_path, out_fields, first.wkbType(), target_epsg
    )
    pref_check, engine = _prepared_prefecture_geometry(pref_geometry)
    national_count = 0
    candidate_count = 0
    written = 0
    try:
        for source_path in sources:
            check_cancelled()
            layer = _open_source_layer(source_path, f"n02_{label}")
            count = layer.featureCount()
            if count > 0:
                national_count += count
            to_target = supplemental._transform(layer.crs(), target_epsg)
            to_geo = supplemental._geo_transform(layer.crs())
            request = QgsFeatureRequest()
            try:
                request.setFilterRect(_source_filter_rect(pref_check, layer.crs()))
            except Exception as exc:
                log(f"N02 {label}: bbox事前抽出を適用できないため全件走査します: {exc}")
            field_names = [f.name() for f in layer.fields()]
            for source_feature in layer.getFeatures(request):
                candidate_count += 1
                if candidate_count % 200 == 0:
                    QCoreApplication.processEvents()
                    check_cancelled()
                    log(
                        f"N02 {label} 処理中: bbox候補 {candidate_count:,}件 / 採用 {written:,}件"
                    )
                if not source_feature.hasGeometry() or source_feature.geometry().isEmpty():
                    continue
                check_geometry = supplemental._copy_geom(
                    source_feature.geometry(), to_geo
                )
                if not _intersects_prefecture(engine, pref_check, check_geometry):
                    continue
                feature = QgsFeature(out_fields)
                feature.setGeometry(
                    supplemental._copy_geom(source_feature.geometry(), to_target)
                )
                feature.setAttributes(
                    [
                        source_feature[name] if name in field_names else None
                        for name in base_names
                    ]
                )
                if not writer.addFeature(feature):
                    raise RuntimeError(f"FGB書き込みに失敗しました: {out_path}")
                written += 1
    finally:
        del writer
        gc.collect()
    if written == 0:
        raise RuntimeError(f"N02 {label}: 対象地物が0件でした: {out_path.name}")
    log(
        f"N02 {label} 完了: 全国 {national_count:,}件 / "
        f"bbox候補 {candidate_count:,}件 / 採用 {written:,}件"
    )
    return out_path


def _patch_transport():
    original = supplemental.SupplementalBuilder.build_transport
    if getattr(original, "_gcham_v112", False):
        return

    def build_transport(self):
        results = []
        for dataset, yy, year, filename_tpl, title, out_tpl, style in supplemental.TRANSPORT_PREF_SPECS:
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
            station_sources = [
                p for p in all_vectors if "station" in p.stem.lower()
            ]
            rail_sources = [
                p
                for p in all_vectors
                if "railroadsection" in p.stem.lower()
                or ("railroad" in p.stem.lower() and "station" not in p.stem.lower())
            ]
        if not station_sources or not rail_sources:
            raise RuntimeError("N02-2025からStation/RailroadSectionを識別できませんでした。")

        station_out = self.data_dir / f"n02_2025_{self.pref_code}_stations.fgb"
        rail_out = self.data_dir / f"n02_2025_{self.pref_code}_railway_lines.fgb"
        for out in (station_out, rail_out):
            qgis_io.remove_existing_layer_for_path(out)
            out.unlink(missing_ok=True)

        _write_n02_prefecture_filtered(
            station_sources,
            station_out,
            self.target_epsg,
            self.pref_geometry,
            self.log,
            self.check_cancelled,
            "鉄道駅",
        )
        _write_n02_prefecture_filtered(
            rail_sources,
            rail_out,
            self.target_epsg,
            self.pref_geometry,
            self.log,
            self.check_cancelled,
            "鉄道路線",
        )
        results.extend(
            [
                supplemental.SupplementalResult(
                    station_out,
                    "鉄道駅_2025_国土数値情報",
                    "交通",
                    "rail_station",
                ),
                supplemental.SupplementalResult(
                    rail_out,
                    "鉄道路線_2025_国土数値情報",
                    "交通",
                    "rail_line",
                ),
            ]
        )
        return results

    build_transport._gcham_v112 = True
    supplemental.SupplementalBuilder.build_transport = build_transport


def _update_elapsed_label(dialog):
    if not hasattr(dialog, "elapsed_label") or not hasattr(dialog, "_elapsed_clock"):
        return
    if not dialog._elapsed_clock.isValid():
        dialog.elapsed_label.setText("経過時間 00:00")
        return
    total_seconds = max(0, dialog._elapsed_clock.elapsed() // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    dialog.elapsed_label.setText(f"経過時間 {minutes:02d}:{seconds:02d}")


def _patch_elapsed_time():
    cls = dialog_module.GCHAMDataPackDialog
    original_build_ui = cls._build_ui
    original_set_running = cls._set_running
    if getattr(original_build_ui, "_gcham_v112", False):
        return

    def _build_ui(self):
        original_build_ui(self)
        self.elapsed_label = QLabel("経過時間 00:00")
        self._elapsed_clock = QElapsedTimer()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(lambda: _update_elapsed_label(self))
        layout = self.layout()
        index = layout.indexOf(self.progress_bar)
        layout.insertWidget(index + 1, self.elapsed_label)

    def _set_running(self, running):
        if running:
            self._elapsed_clock.start()
            self._elapsed_timer.start()
            _update_elapsed_label(self)
        original_set_running(self, running)
        if not running and hasattr(self, "_elapsed_timer"):
            _update_elapsed_label(self)
            self._elapsed_timer.stop()

    _build_ui._gcham_v112 = True
    _set_running._gcham_v112 = True
    cls._build_ui = _build_ui
    cls._set_running = _set_running


def apply_patches():
    global _APPLIED
    if _APPLIED:
        return
    _patch_facilities()
    _patch_transport()
    _patch_processor_build()
    _patch_elapsed_time()
    _APPLIED = True
