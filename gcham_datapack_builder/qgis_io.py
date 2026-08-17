# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import gc
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from qgis.PyQt.QtCore import QMetaType, QUrl, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (
    Qgis,
    QgsBlockingNetworkRequest,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFillSymbol,
    QgsFeatureSink,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsGradientColorRamp,
    QgsGradientStop,
    QgsGraduatedSymbolRenderer,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsRendererRangeLabelFormat,
    QgsSpatialIndex,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

from .constants import GEOGRAPHIC_CRS_EPSG
from .core_logic import mesh250_bbox, mesh250_center


class CancelledError(RuntimeError):
    pass


def _enum_member(owner, nested_name: str, member_name: str):
    """Return scoped enum member on QGIS 4 and flat SIP alias on QGIS 3."""
    nested = getattr(owner, nested_name, None)
    if nested is not None and hasattr(nested, member_name):
        return getattr(nested, member_name)
    return getattr(owner, member_name)


def _qmeta(name: str):
    enum = getattr(QMetaType, "Type", QMetaType)
    return getattr(enum, name)


def qmeta_string():
    return _qmeta("QString")


def qmeta_int64():
    return _qmeta("LongLong")


def qmeta_double():
    return _qmeta("Double")


def download_file(
    url: str,
    destination: Path,
    log: Callable[[str], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
    force_refresh: bool = True,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = QNetworkRequest(QUrl(url))
    blocking = QgsBlockingNetworkRequest()
    if progress:
        blocking.downloadProgress.connect(progress)
    err = blocking.get(request, force_refresh)
    if err != _enum_member(QgsBlockingNetworkRequest, "ErrorCode", "NoError"):
        raise RuntimeError(f"ダウンロード失敗: {url}\n{blocking.errorMessage()}")
    content = bytes(blocking.reply().content())
    if not content:
        raise RuntimeError(f"空のレスポンスを受信しました: {url}")
    tmp = destination.with_suffix(destination.suffix + ".part")
    tmp.write_bytes(content)
    tmp.replace(destination)
    if log:
        log(f"ダウンロード完了: {destination.name} ({len(content):,} bytes)")
    return destination


def valid_zip(path: Path, require_nonempty: bool = True) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 22 or not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            files = [i for i in zf.infolist() if not i.is_dir()]
            return bool(files) if require_nonempty else True
    except (OSError, zipfile.BadZipFile):
        return False


def safe_extract_zip(zip_path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (destination / member.filename).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError(f"不正なZIPパスを検出しました: {member.filename}")
        zf.extractall(destination)
    return destination


def find_n03_vector(extracted_dir: Path) -> Path:
    candidates = []
    for suffix, rank in ((".shp", 0), (".geojson", 1), (".gml", 2)):
        for p in extracted_dir.rglob(f"*{suffix}"):
            name = p.name.upper()
            if name.startswith("N03"):
                candidates.append((rank, len(str(p)), p))
    if not candidates:
        raise RuntimeError("N03 ZIP内に行政区域のSHAPE/GeoJSON/GMLが見つかりません。")
    return sorted(candidates)[0][2]


@dataclass
class Municipality:
    code: str
    name: str
    geometry: QgsGeometry
    attributes: dict[str, object]


class MunicipalityIndex:
    def __init__(self, municipalities: Iterable[Municipality]):
        self.municipalities = sorted(municipalities, key=lambda m: m.code)
        self._by_id: dict[int, Municipality] = {}
        self._index = QgsSpatialIndex()
        for fid, muni in enumerate(self.municipalities, start=1):
            feat = QgsFeature()
            feat.setId(fid)
            feat.setGeometry(muni.geometry)
            self._index.addFeature(feat)
            self._by_id[fid] = muni

    def assign(self, key_code: str) -> Municipality | None:
        lon, lat = mesh250_center(key_code)
        point = QgsPointXY(lon, lat)
        point_geom = QgsGeometry.fromPointXY(point)
        rect = QgsRectangle(lon, lat, lon, lat)
        candidates = [self._by_id[i] for i in self._index.intersects(rect)]
        inside = [m for m in candidates if m.geometry.contains(point_geom)]
        if len(inside) == 1:
            return inside[0]
        if len(inside) > 1:
            return sorted(inside, key=lambda m: m.code)[0]

        # Exact boundary case: use maximum overlap of the intact 250 m mesh.
        mesh_geom = mesh_geometry(key_code)
        overlap_candidates = candidates
        if not overlap_candidates:
            overlap_candidates = [
                self._by_id[i] for i in self._index.intersects(mesh_geom.boundingBox())
            ]
        scored = []
        for muni in overlap_candidates:
            if not muni.geometry.intersects(mesh_geom):
                continue
            inter = muni.geometry.intersection(mesh_geom)
            if not inter.isEmpty():
                scored.append((inter.area(), muni.code, muni))
        if not scored:
            return None
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][2]


def load_and_dissolve_n03(vector_path: Path) -> tuple[list[Municipality], QgsFields]:
    layer = QgsVectorLayer(str(vector_path), "N03", "ogr")
    if not layer.isValid():
        raise RuntimeError(f"N03行政区域を読み込めません: {vector_path}")
    names = set(layer.fields().names())
    if "N03_007" not in names:
        raise RuntimeError("N03データに N03_007 がありません。")
    if "N03_004" not in names:
        raise RuntimeError("N03データに N03_004 がありません。")

    geographic_crs = QgsCoordinateReferenceSystem.fromEpsgId(GEOGRAPHIC_CRS_EPSG)
    source_crs = layer.crs()
    transform_to_geographic = None
    if source_crs.isValid() and source_crs != geographic_crs:
        transform_to_geographic = QgsCoordinateTransform(
            source_crs, geographic_crs, QgsProject.instance()
        )

    keep_names = [n for n in layer.fields().names() if n.startswith("N03_")]
    out_fields = QgsFields()
    for name in keep_names:
        out_fields.append(QgsField(layer.fields().field(name)))

    grouped: dict[str, dict] = {}
    for feat in layer.getFeatures():
        raw_code = feat["N03_007"]
        if raw_code is None:
            continue
        code = str(raw_code).strip()
        if not code:
            continue
        if code.isdigit():
            code = code.zfill(5)
        name5 = str(feat["N03_005"] or "").strip() if "N03_005" in names else ""
        name4 = str(feat["N03_004"] or "").strip()
        muni_name = name5 or name4
        if not muni_name:
            continue
        entry = grouped.setdefault(
            code,
            {
                "name": muni_name,
                "geoms": [],
                "attributes": {n: feat[n] for n in keep_names},
            },
        )
        geom = QgsGeometry(feat.geometry())
        if transform_to_geographic is not None:
            geom.transform(transform_to_geographic)
        entry["geoms"].append(geom)
        if name5:
            entry["name"] = name5

    municipalities: list[Municipality] = []
    for code in sorted(grouped):
        entry = grouped[code]
        geoms = entry["geoms"]
        geom = QgsGeometry.unaryUnion(geoms) if len(geoms) > 1 else QgsGeometry(geoms[0])
        if geom.isNull() or geom.isEmpty():
            continue
        if not geom.isMultipart():
            geom.convertToMultiType()
        municipalities.append(
            Municipality(code, entry["name"], geom, entry["attributes"])
        )
    if not municipalities:
        raise RuntimeError("N03から自治体を抽出できませんでした。")
    return municipalities, out_fields


def mesh_geometry(key_code: str) -> QgsGeometry:
    west, south, east, north = mesh250_bbox(key_code)
    ring = [
        QgsPointXY(west, south), QgsPointXY(west, north),
        QgsPointXY(east, north), QgsPointXY(east, south),
        QgsPointXY(west, south),
    ]
    geom = QgsGeometry.fromPolygonXY([ring])
    geom.convertToMultiType()
    return geom


def merged_mesh_geometry(key_code: str, gassan_codes: list[str]) -> QgsGeometry:
    geoms = [mesh_geometry(key_code)]
    geoms.extend(mesh_geometry(code) for code in gassan_codes)
    geom = QgsGeometry.unaryUnion(geoms) if len(geoms) > 1 else geoms[0]
    if not geom.isMultipart():
        geom.convertToMultiType()
    return geom


def output_crs(epsg: int) -> QgsCoordinateReferenceSystem:
    crs = QgsCoordinateReferenceSystem.fromEpsgId(int(epsg))
    if not crs.isValid():
        raise RuntimeError(f"出力CRS EPSG:{epsg} をQGISで作成できません。")
    return crs


def geometry_transformer(target_epsg: int) -> QgsCoordinateTransform | None:
    if int(target_epsg) == GEOGRAPHIC_CRS_EPSG:
        return None
    return QgsCoordinateTransform(
        QgsCoordinateReferenceSystem.fromEpsgId(GEOGRAPHIC_CRS_EPSG),
        output_crs(target_epsg),
        QgsProject.instance(),
    )


def transform_geometry(geometry: QgsGeometry, transformer: QgsCoordinateTransform | None) -> QgsGeometry:
    geom = QgsGeometry(geometry)
    if transformer is not None:
        geom.transform(transformer)
    if not geom.isMultipart():
        geom.convertToMultiType()
    return geom


def create_fgb_writer(path: Path, fields: QgsFields, target_epsg: int) -> QgsVectorFileWriter:
    path.parent.mkdir(parents=True, exist_ok=True)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "FlatGeobuf"
    options.fileEncoding = "UTF-8"
    options.actionOnExistingFile = _enum_member(
        QgsVectorFileWriter, "ActionOnExistingFile", "CreateOrOverwriteFile"
    )
    options.layerName = path.stem
    options.layerOptions = ["SPATIAL_INDEX=YES"]
    writer = QgsVectorFileWriter.create(
        str(path),
        fields,
        Qgis.WkbType.MultiPolygon,
        output_crs(target_epsg),
        QgsProject.instance().transformContext(),
        options,
    )
    if writer is None or writer.hasError() != _enum_member(
        QgsVectorFileWriter, "WriterError", "NoError"
    ):
        msg = writer.errorMessage() if writer is not None else "writer is None"
        raise RuntimeError(f"FlatGeobufを作成できません: {path}\n{msg}")
    return writer


def close_writer(writer: QgsVectorFileWriter | None) -> None:
    """Release an OGR-backed writer reference and force Python cleanup.

    FlatGeobuf writes its index/footer when the dataset is closed. QGIS'
    QgsVectorFileWriter does not require an explicit flush call here; releasing
    the SIP wrapper is the reliable cross-version finalization path.
    """
    if writer is None:
        return
    del writer
    gc.collect()


def close_writers(writers: dict[str, QgsVectorFileWriter]) -> None:
    # Pop one at a time so the dictionary cannot retain a writer reference.
    while writers:
        _key, writer = writers.popitem()
        del writer
    gc.collect()


def write_admin_fgb(
    path: Path,
    muni: Municipality,
    source_fields: QgsFields,
    target_epsg: int,
    transformer: QgsCoordinateTransform | None = None,
) -> None:
    writer = create_fgb_writer(path, source_fields, target_epsg)
    feat = QgsFeature(source_fields)
    feat.setGeometry(transform_geometry(muni.geometry, transformer))
    attrs = [muni.attributes.get(field.name()) for field in source_fields]
    feat.setAttributes(attrs)
    if not writer.addFeature(feat, _enum_member(QgsFeatureSink, "Flag", "FastInsert")):
        msg = writer.errorMessage()
        del writer
        gc.collect()
        raise RuntimeError(f"行政区域FGBの書き込みに失敗しました: {path}\n{msg}")
    writer.flushBuffer()
    del writer
    gc.collect()


def remove_existing_layer_for_path(path: Path) -> None:
    canonical = os.path.normcase(os.path.abspath(str(path)))
    project = QgsProject.instance()
    remove_ids = []
    for layer_id, layer in project.mapLayers().items():
        source = layer.source().split("|")[0]
        if os.path.normcase(os.path.abspath(source)) == canonical:
            remove_ids.append(layer_id)
    if remove_ids:
        project.removeMapLayers(remove_ids)


def _mm_render_unit():
    return _enum_member(Qgis, "RenderUnit", "Millimeters")


def style_admin_layer(layer: QgsVectorLayer) -> None:
    # Match the requested transparent administrative-boundary style.
    symbol = QgsFillSymbol.createSimple(
        {
            "color": "255,255,255,0",
            "outline_color": "255,76,0,255",
            "outline_width": "0.96",
            "outline_style": "solid",
        }
    )
    symbol.setOpacity(0.70)
    sl = symbol.symbolLayer(0)
    if sl is not None:
        sl.setStrokeWidth(0.96)
        sl.setStrokeWidthUnit(_mm_render_unit())
        pen_join_scope = getattr(Qt, "PenJoinStyle", Qt)
        sl.setPenJoinStyle(getattr(pen_join_scope, "BevelJoin"))
    layer.renderer().setSymbol(symbol)

    # Label with ward name when present, otherwise municipality name.
    settings = QgsPalLayerSettings()
    settings.fieldName = 'coalesce(nullif("N03_005", \'\'), "N03_004")'
    settings.isExpression = True
    text_format = QgsTextFormat()
    text_format.setSize(10.0)
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.0)
    buffer.setSizeUnit(_mm_render_unit())
    buffer.setColor(QColor(255, 255, 255))
    buffer.setOpacity(0.80)
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()


def _jenks_mode():
    return _enum_member(QgsGraduatedSymbolRenderer, "Mode", "Jenks")


def style_population_layer(layer: QgsVectorLayer, value_field: str = "人口（総数）") -> None:
    if layer.fields().indexOf(value_field) < 0:
        return

    # Blue -> near white -> red, 10 natural-break classes, as requested.
    symbol = QgsFillSymbol.createSimple(
        {
            "color": "255,255,255,255",
            "outline_color": "255,255,255,0",
            "outline_width": "0",
        }
    )
    symbol.setOpacity(0.70)
    ramp = QgsGradientColorRamp(
        QColor(5, 113, 176),
        QColor(202, 0, 32),
        False,
        [QgsGradientStop(0.50, QColor(247, 247, 247))],
    )
    try:
        renderer = QgsGraduatedSymbolRenderer.createRenderer(
            layer,
            value_field,
            10,
            _jenks_mode(),
            symbol,
            ramp,
            QgsRendererRangeLabelFormat("%1 - %2", 0, True),
        )
    except TypeError:
        # Fallback for bindings with the shorter overload. QGIS will generate
        # default range labels for this overload, so no silent exception is needed.
        renderer = QgsGraduatedSymbolRenderer.createRenderer(
            layer, value_field, 10, _jenks_mode(), symbol, ramp
        )
    if renderer is not None:
        layer.setRenderer(renderer)
        layer.triggerRepaint()


def add_layer_to_group(
    path: Path,
    display_name: str,
    group_name: str,
    index: int | None = None,
    style_kind: str | None = None,
):
    remove_existing_layer_for_path(path)
    layer = QgsVectorLayer(str(path), display_name, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"作成済みFGBをQGISへ追加できません: {path}")
    if style_kind == "admin":
        style_admin_layer(layer)
    elif style_kind == "population":
        style_population_layer(layer)
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup(group_name)
    if group is None:
        group = root.addGroup(group_name)
    project.addMapLayer(layer, False)
    if index is None:
        group.addLayer(layer)
    else:
        group.insertLayer(index, layer)
    return layer
