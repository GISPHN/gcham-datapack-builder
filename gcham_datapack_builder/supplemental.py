# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import csv
import gc
import html
import json
import math
import re
from datetime import date
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlencode, urljoin, urlparse

from qgis.PyQt.QtCore import QByteArray, QUrl, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (
    Qgis,
    QgsBlockingNetworkRequest,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsFields,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsLineSymbol,
    QgsMapClippingRegion,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRendererCategory,
    QgsSimpleLineSymbolLayer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)

from .constants import GEOGRAPHIC_CRS_EPSG
from .qgis_io import (
    CancelledError,
    Municipality,
    download_file,
    output_crs,
    qmeta_string,
    remove_existing_layer_for_path,
    safe_extract_zip,
    valid_zip,
)

KSJ_BASE = "https://nlftp.mlit.go.jp/ksj/gml/data"
GSI_SHELTER_PAGE = "https://hinanmap.gsi.go.jp/hinanjocp/hinanbasho/koukaidate.html"
JSHIS_DOWNLOAD_PAGE = "https://www.j-shis.bosai.go.jp/map/JSHIS2/download.html?lang=jp"

FACILITY_SPECS = (
    ("P28", "22", "2022", "P28-22_{pref}.zip", "国・都道府県の機関", "p28_2022_{pref}_facilities.fgb", "p28"),
    ("P05", "22", "2022", "P05-22_{pref}_GML.zip", "市町村役場等及び公的集会施設", "p05_2022_{pref}_facilities.fgb", "p05"),
    ("P04", "20", "2020", "P04-20_{pref}_GML.zip", "医療機関", "p04_2020_{pref}_medical.fgb", "p04"),
    ("A27", "23", "2023", "A27-23_{pref}_GML.zip", "小学校区", "a27_2023_{pref}_school_districts.fgb", "a27"),
    ("P29", "23", "2023", "P29-23_{pref}_GML.zip", "学校", "p29_2023_{pref}_schools.fgb", "p29"),
)

TRANSPORT_PREF_SPECS = (
    ("P11", "22", "2022", "P11-22_{pref}_SHP.zip", "バス停留所", "p11_2022_{pref}_bus_stops.fgb", "p11"),
    ("N07", "22", "2022", "N07-22_{pref}_SHP.zip", "バスルート", "n07_2022_{pref}_bus_routes.fgb", "n07"),
)

P29_LABELS = {
    "16001": "小学校", "16002": "中学校", "16003": "中等教育学校",
    "16004": "高等学校", "16005": "高等専門学校", "16006": "短期大学",
    "16007": "大学", "16011": "幼稚園", "16012": "特別支援学校",
    "16013": "幼保連携型認定こども園", "16014": "義務教育学校",
    "16015": "各種学校", "16016": "専修学校",
}

ROAD_MAPS = {
    "道路の種別N13_002": ("N13_002", {1: "通常部", 2: "庭園路", 3: "徒歩道", 4: "石段", 5: "不明"}),
    "道路の分類N13_003": ("N13_003", {1: "国道", 2: "都道府県道", 3: "市区町村道等", 4: "高速自動車国道等", 5: "その他", 6: "不明"}),
    "道路の状態N13_004": ("N13_004", {1: "通常部", 2: "橋・高架", 3: "トンネル", 4: "雪囲い", 5: "建設中", 6: "その他", 7: "不明"}),
    "幅員の区分N13_006": ("N13_006", {1: "3m未満", 2: "3m-5.5m未満", 3: "5.5m-13m未満", 4: "13m-19.5m未満", 5: "19.5m以上", 6: "不明"}),
    "有料の区分N13_007": ("N13_007", {1: "無料", 2: "有料"}),
}

ROAD_WIDTHS = {
    "3m未満": 0.26,
    "3m-5.5m未満": 0.46,
    "5.5m-13m未満": 0.66,
    "13m-19.5m未満": 0.86,
    "19.5m以上": 1.06,
}

BACKGROUND_TILES = (
    ("OpenStreetMap(Standard)_©OpenStreetMap Contributors", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", 2, 18, True, 0.70),
    ("全国最新写真_地理院タイル", "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg", 2, 18, False, 0.70),
    ("陰影起伏図_地理院タイル", "https://cyberjapandata.gsi.go.jp/xyz/hillshademap/{z}/{x}/{y}.png", 2, 16, False, 1.00),
)

CATEGORY_COLORS = (
    "#e78ac3", "#66c2a5", "#ffd92f", "#8da0cb", "#a676d2", "#e78ac3",
    "#4daf4a", "#fc8d62", "#66c2a5", "#a6d854", "#7ae582", "#55d6be", "#e15759",
)


def _enum_member(owner, nested_name: str, member_name: str):
    nested = getattr(owner, nested_name, None)
    if nested is not None and hasattr(nested, member_name):
        return getattr(nested, member_name)
    return getattr(owner, member_name)


def _mm_unit():
    return _enum_member(Qgis, "RenderUnit", "Millimeters")


def _qt_join(name: str):
    scope = getattr(Qt, "PenJoinStyle", Qt)
    return getattr(scope, name)


def _qt_cap(name: str):
    scope = getattr(Qt, "PenCapStyle", Qt)
    return getattr(scope, name)


def _source_vector_files(folder: Path, preferred: str | None = None) -> list[Path]:
    files = sorted(folder.rglob("*.shp"))
    if not files:
        files = sorted(folder.rglob("*.gml"))
    if preferred:
        hits = [p for p in files if preferred.lower() in p.stem.lower()]
        if hits:
            return hits
    if not files:
        raise RuntimeError(f"ベクタデータを展開フォルダから検出できません: {folder}")
    return files


def _copy_fields(source: QgsFields, extra_names: Iterable[str] = ()) -> QgsFields:
    out = QgsFields()
    for field in source:
        out.append(QgsField(field))
    for name in extra_names:
        if out.indexOf(name) < 0:
            out.append(QgsField(name, qmeta_string(), "", 20))
    return out


def _create_writer(path: Path, fields: QgsFields, wkb_type, target_epsg: int) -> QgsVectorFileWriter:
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
        str(path), fields, wkb_type, output_crs(target_epsg),
        QgsProject.instance().transformContext(), options,
    )
    if writer is None or writer.hasError() != _enum_member(QgsVectorFileWriter, "WriterError", "NoError"):
        msg = writer.errorMessage() if writer is not None else "writer is None"
        raise RuntimeError(f"FlatGeobufを作成できません: {path}\n{msg}")
    return writer


def _transform(source_crs: QgsCoordinateReferenceSystem, target_epsg: int):
    target = output_crs(target_epsg)
    if source_crs == target:
        return None
    return QgsCoordinateTransform(source_crs, target, QgsProject.instance())


def _geo_transform(source_crs: QgsCoordinateReferenceSystem):
    geo = QgsCoordinateReferenceSystem.fromEpsgId(GEOGRAPHIC_CRS_EPSG)
    if source_crs == geo:
        return None
    return QgsCoordinateTransform(source_crs, geo, QgsProject.instance())


def _copy_geom(geom: QgsGeometry, transform: QgsCoordinateTransform | None) -> QgsGeometry:
    out = QgsGeometry(geom)
    if transform is not None:
        out.transform(transform)
    return out


def _write_merged_vectors(
    sources: list[Path], out_path: Path, target_epsg: int,
    pref_geometry: QgsGeometry | None = None,
    extra_maps: dict[str, tuple[str, dict[int, str]]] | None = None,
    clip_to_pref: bool = False,
) -> Path:
    if not sources:
        raise RuntimeError("入力ベクタがありません。")
    first = QgsVectorLayer(str(sources[0]), "source", "ogr")
    if not first.isValid():
        raise RuntimeError(f"入力データを開けません: {sources[0]}")
    extras = tuple((extra_maps or {}).keys())
    base_names = [f.name() for f in first.fields()]
    out_fields = _copy_fields(first.fields(), extras)
    writer_wkb = first.wkbType()
    if clip_to_pref:
        writer_wkb = QgsWkbTypes.multiType(writer_wkb)
    writer = _create_writer(out_path, out_fields, writer_wkb, target_epsg)
    written = 0
    try:
        for source_path in sources:
            layer = QgsVectorLayer(str(source_path), "source", "ogr")
            if not layer.isValid():
                raise RuntimeError(f"入力データを開けません: {source_path}")
            to_target = _transform(layer.crs(), target_epsg)
            to_geo = _geo_transform(layer.crs()) if pref_geometry is not None else None
            field_names = [f.name() for f in layer.fields()]
            for src in layer.getFeatures():
                if not src.hasGeometry() or src.geometry().isEmpty():
                    continue
                check_geom = None
                if pref_geometry is not None:
                    check_geom = _copy_geom(src.geometry(), to_geo)
                    if not check_geom.intersects(pref_geometry):
                        continue
                feat = QgsFeature(out_fields)
                if clip_to_pref and check_geom is not None:
                    geom = check_geom.intersection(pref_geometry)
                    if geom.isEmpty():
                        continue
                    geo_crs = QgsCoordinateReferenceSystem.fromEpsgId(GEOGRAPHIC_CRS_EPSG)
                    geo_to_target = _transform(geo_crs, target_epsg)
                    if geo_to_target is not None:
                        geom.transform(geo_to_target)
                    if not geom.isMultipart():
                        geom.convertToMultiType()
                else:
                    geom = _copy_geom(src.geometry(), to_target)
                feat.setGeometry(geom)
                attrs = [src[name] if name in field_names else None for name in base_names]
                for _new_name, (source_name, mapping) in (extra_maps or {}).items():
                    raw = src[source_name] if source_name in field_names else None
                    try:
                        key = int(raw) if raw is not None and str(raw).strip() else None
                    except (TypeError, ValueError):
                        key = None
                    attrs.append(mapping.get(key))
                feat.setAttributes(attrs)
                if not writer.addFeature(feat, _enum_member(QgsFeatureSink, "Flag", "FastInsert")):
                    raise RuntimeError(f"FGB書き込みに失敗しました: {out_path}")
                written += 1
    finally:
        del writer
        gc.collect()
    if written == 0:
        raise RuntimeError(f"対象地物が0件でした: {out_path.name}")
    return out_path


def first_mesh_codes(pref_geometry: QgsGeometry) -> list[str]:
    """Return Japanese first-level mesh codes intersecting a JGD2011 polygon."""
    bbox = pref_geometry.boundingBox()
    row_min = max(0, int(math.floor(bbox.yMinimum() * 1.5)) - 1)
    row_max = int(math.floor(bbox.yMaximum() * 1.5)) + 1
    col_min = int(math.floor(bbox.xMinimum())) - 101
    col_max = int(math.floor(bbox.xMaximum())) - 99
    result = []
    for row in range(row_min, row_max + 1):
        south = row * (2.0 / 3.0)
        north = south + (2.0 / 3.0)
        for col in range(col_min, col_max + 1):
            west = 100.0 + col
            east = west + 1.0
            ring = [
                QgsPointXY(west, south), QgsPointXY(west, north),
                QgsPointXY(east, north), QgsPointXY(east, south),
                QgsPointXY(west, south),
            ]
            mesh = QgsGeometry.fromPolygonXY([ring])
            if not mesh.intersects(pref_geometry):
                continue
            overlap = mesh.intersection(pref_geometry)
            if not overlap.isEmpty() and overlap.area() > 0.0:
                result.append(f"{row:02d}{col:02d}")
    return sorted(set(result))



def _tag_attrs(tag: str) -> dict[str, str]:
    """Parse a small HTML tag attribute subset used by the J-SHIS download form."""
    attrs: dict[str, str] = {}
    pattern = re.compile(
        r"([:\w-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
        re.IGNORECASE,
    )
    for match in pattern.finditer(tag):
        attrs[match.group(1).lower()] = html.unescape(
            match.group(2) or match.group(3) or match.group(4) or ""
        )
    return attrs


def _choice_score(text: str, mesh_code: str) -> int:
    """Score HTML option/radio values against the requested PSHM settings."""
    value = html.unescape(text).lower()
    score = 0
    desired = (
        (("y2024", "2024", "2024年"), 9),
        (("ttl_mttl", "all earthquake", "all earthquakes", "全ての地震", "全地震"), 9),
        (("max", "最大"), 9),
        (("shp", "shape", "シェープ"), 8),
        (("zip",), 8),
        (("first", "1st", "1次", "mesh", "メッシュ"), 3),
    )
    for tokens, weight in desired:
        if any(token in value for token in tokens):
            score += weight
    if mesh_code in value:
        score += 20
    return score


def _jshis_forms(page_html: str) -> list[dict]:
    """Extract ordinary HTML forms from the official J-SHIS download page."""
    forms: list[dict] = []
    for match in re.finditer(r"<form\b([^>]*)>(.*?)</form>", page_html, re.I | re.S):
        attrs = _tag_attrs(match.group(1))
        body = match.group(2)
        inputs = []
        for input_match in re.finditer(r"<input\b[^>]*>", body, re.I | re.S):
            tag = input_match.group(0)
            item = _tag_attrs(tag)
            item["checked"] = "1" if re.search(r"\bchecked\b", tag, re.I) else "0"
            inputs.append(item)
        selects = []
        for select_match in re.finditer(r"<select\b([^>]*)>(.*?)</select>", body, re.I | re.S):
            select_attrs = _tag_attrs(select_match.group(1))
            options = []
            for option_match in re.finditer(
                r"<option\b([^>]*)>(.*?)</option>", select_match.group(2), re.I | re.S
            ):
                option_attrs = _tag_attrs(option_match.group(1))
                label = re.sub(r"<[^>]+>", "", option_match.group(2))
                option_attrs["label"] = html.unescape(label).strip()
                option_attrs["selected"] = (
                    "1" if re.search(r"\bselected\b", option_match.group(1), re.I) else "0"
                )
                options.append(option_attrs)
            selects.append({"attrs": select_attrs, "options": options})
        forms.append({
            "action": attrs.get("action", ""),
            "method": attrs.get("method", "get").lower(),
            "body": body,
            "inputs": inputs,
            "selects": selects,
        })
    return forms


def _jshis_form_payload(form: dict, mesh_code: str) -> tuple[list[tuple[str, str]], int]:
    """Build one first-mesh PSHM request from an HTML form discovered at runtime."""
    pairs: list[tuple[str, str]] = []
    score = 0
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in form["inputs"]:
        name = item.get("name", "")
        if not name:
            continue
        input_type = item.get("type", "text").lower()
        if input_type in {"radio", "checkbox"}:
            grouped.setdefault(name, []).append(item)
            continue
        value = item.get("value", "")
        searchable = " ".join((name, item.get("id", ""), value))
        lower = searchable.lower()
        if "mesh" in lower or "メッシュ" in searchable:
            value = mesh_code
            score += 8
        pairs.append((name, value))

    for name, items in grouped.items():
        ranked = []
        for item in items:
            searchable = " ".join(
                (name, item.get("id", ""), item.get("value", ""), item.get("title", ""))
            )
            ranked.append((_choice_score(searchable, mesh_code), item))
        ranked.sort(key=lambda x: x[0], reverse=True)
        best_score, best = ranked[0]
        if best_score > 0:
            pairs.append((name, best.get("value", "on")))
            score += best_score
        else:
            checked = next((i for i in items if i.get("checked") == "1"), None)
            if checked is not None:
                pairs.append((name, checked.get("value", "on")))

    for select in form["selects"]:
        attrs = select["attrs"]
        name = attrs.get("name", "")
        if not name:
            continue
        ranked = []
        for option in select["options"]:
            searchable = " ".join((name, option.get("value", ""), option.get("label", "")))
            ranked.append((_choice_score(searchable, mesh_code), option))
        ranked.sort(key=lambda x: x[0], reverse=True)
        best_score, best = ranked[0] if ranked else (0, None)
        if best is not None and best_score > 0:
            pairs.append((name, best.get("value", best.get("label", ""))))
            score += best_score
        else:
            selected = next((o for o in select["options"] if o.get("selected") == "1"), None)
            if selected is None and select["options"]:
                selected = select["options"][0]
            if selected is not None:
                pairs.append((name, selected.get("value", selected.get("label", ""))))

    if mesh_code in form["body"] and not any(mesh_code == value for _name, value in pairs):
        for item in form["inputs"]:
            name = item.get("name", "")
            value = item.get("value", "")
            if name and re.fullmatch(r"\d{4}", value or "") and value == mesh_code:
                pairs.append((name, value))
                score += 20
                break
    return pairs, score


def _zip_urls_from_text(text: str, base_url: str, mesh_code: str) -> list[str]:
    """Return ZIP links embedded in HTML/JSON/JavaScript responses."""
    urls = []
    pattern = re.compile(r"(?:href|src)?\s*[:=]?\s*[\"']([^\"']+?\.zip(?:\?[^\"']*)?)[\"']", re.I)
    for match in pattern.finditer(text):
        candidate = html.unescape(match.group(1)).replace("\\/", "/")
        absolute = urljoin(base_url, candidate)
        if mesh_code in absolute or "download" in absolute.lower() or "pshm" in absolute.lower():
            if absolute not in urls:
                urls.append(absolute)
    return urls


def _looks_like_zip(content: bytes) -> bool:
    return content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))


def _pref_union(municipalities: list[Municipality]) -> QgsGeometry:
    geom = QgsGeometry.unaryUnion([QgsGeometry(m.geometry) for m in municipalities])
    if geom.isEmpty():
        raise RuntimeError("都道府県行政区域を作成できませんでした。")
    return geom


def _apply_label(
    layer: QgsVectorLayer, field_name: str, buffer_opacity: float = 1.0,
    horizontal: bool = False, enabled: bool = False,
):
    if layer.fields().indexOf(field_name) < 0:
        return
    settings = QgsPalLayerSettings()
    settings.fieldName = field_name
    if horizontal:
        placement_scope = getattr(Qgis, "LabelPlacement", Qgis)
        if hasattr(placement_scope, "Horizontal"):
            settings.placement = getattr(placement_scope, "Horizontal")
        settings.obstacle = True
    fmt = QgsTextFormat()
    fmt.setSize(10.0)
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.0)
    buffer.setSizeUnit(_mm_unit())
    buffer.setColor(QColor("white"))
    buffer.setOpacity(buffer_opacity)
    fmt.setBuffer(buffer)
    settings.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    # Supplemental groups keep label settings ready, but labels are hidden by default.
    layer.setLabelsEnabled(enabled)


def _marker(color: str, size: float = 2.0, outline: str = "#ffffff", outline_width: float = 0.4):
    sym = QgsMarkerSymbol.createSimple({
        "name": "circle", "color": color, "outline_color": outline,
        "outline_width": str(outline_width), "size": str(size),
    })
    sym.setSize(size)
    sym.setSizeUnit(_mm_unit())
    return sym


def _line(color: str, width: float, join: str = "BevelJoin", cap: str = "SquareCap"):
    sym = QgsLineSymbol.createSimple({"line_color": color, "line_width": str(width), "line_style": "solid"})
    sl = sym.symbolLayer(0)
    if sl is not None:
        sl.setWidth(width)
        sl.setWidthUnit(_mm_unit())
        if hasattr(sl, "setPenJoinStyle"):
            sl.setPenJoinStyle(_qt_join(join))
        if hasattr(sl, "setPenCapStyle"):
            sl.setPenCapStyle(_qt_cap(cap))
    return sym


def _categorized(layer: QgsVectorLayer, field: str, labels: dict[str, str], visible: set[str] | None = None):
    idx = layer.fields().indexOf(field)
    if idx < 0:
        return
    actual = sorted(layer.uniqueValues(idx), key=lambda v: str(v))
    categories = []
    for i, value in enumerate(actual):
        key = str(value)
        label = labels.get(key, key)
        cat = QgsRendererCategory(value, _marker(CATEGORY_COLORS[i % len(CATEGORY_COLORS)]), label)
        if visible is not None and hasattr(cat, "setRenderState"):
            cat.setRenderState(key in visible)
        categories.append(cat)
    layer.setRenderer(QgsCategorizedSymbolRenderer(field, categories))


def style_vector(layer: QgsVectorLayer, kind: str):
    if kind == "p28":
        _categorized(layer, "P28_005", {"0": "その他", "1": "国", "2": "都道府県", "3": "市区町村", "4": "民間"}, {"2"})
        _apply_label(layer, "P28_003", 1.0)
    elif kind == "p05":
        _categorized(layer, "P05_002", {"1": "市区町村の本庁", "2": "市区町村の支所等", "3": "その他行政サービス施設", "4": "公立公民館", "5": "集会施設"}, {"1"})
        _apply_label(layer, "P05_003", 1.0)
    elif kind == "p04":
        _categorized(layer, "P04_001", {"1": "病院", "2": "診療所", "3": "歯科診療所"}, {"1"})
        _apply_label(layer, "P04_002", 1.0)
    elif kind == "a27":
        sym = QgsFillSymbol.createSimple({"color": "255,255,255,0", "outline_color": "0,0,0", "outline_width": "0.36", "outline_style": "dot"})
        sl = sym.symbolLayer(0)
        if sl is not None:
            sl.setStrokeWidth(0.36)
            sl.setStrokeWidthUnit(_mm_unit())
            if hasattr(sl, "setPenJoinStyle"):
                sl.setPenJoinStyle(_qt_join("BevelJoin"))
        layer.renderer().setSymbol(sym)
        _apply_label(layer, "A27_004", 1.0)
    elif kind == "p29":
        _categorized(layer, "P29_003", P29_LABELS, None)
        _apply_label(layer, "P29_004", 1.0)
    elif kind == "p11":
        layer.renderer().setSymbol(_marker("#ffffff", 2.0, "#555555", 0.4))
        _apply_label(layer, "P11_001", 0.80)
    elif kind == "n07":
        layer.renderer().setSymbol(_line("#91522d", 0.26))
    elif kind == "rail_station":
        black = QgsSimpleLineSymbolLayer(QColor("#000000"), 1.06)
        black.setWidthUnit(_mm_unit())
        black.setPenJoinStyle(_qt_join("RoundJoin"))
        black.setPenCapStyle(_qt_cap("RoundCap"))
        white = QgsSimpleLineSymbolLayer(QColor("#ffffff"), 0.86)
        white.setWidthUnit(_mm_unit())
        white.setPenJoinStyle(_qt_join("RoundJoin"))
        white.setPenCapStyle(_qt_cap("RoundCap"))
        sym = QgsLineSymbol([black, white])
        layer.renderer().setSymbol(sym)
        _apply_label(layer, "N02_005", 1.0, horizontal=True)
    elif kind == "rail_line":
        layer.renderer().setSymbol(_line("#666666", 0.26))
    elif kind == "road":
        field = "幅員の区分N13_006"
        idx = layer.fields().indexOf(field)
        if idx >= 0:
            actual = layer.uniqueValues(idx)
            order = list(ROAD_WIDTHS)
            cats = []
            for label in order:
                if label not in {str(v) for v in actual}:
                    continue
                cats.append(QgsRendererCategory(label, _line("#777777", ROAD_WIDTHS[label]), label))
            layer.setRenderer(QgsCategorizedSymbolRenderer(field, cats))
    elif kind == "gsi_emergency":
        layer.renderer().setSymbol(_marker("#ff1744", 2.0, "#ffffff", 0.4))
        _apply_label(layer, "施設・場所名", 1.0)
    elif kind == "gsi_shelter":
        layer.renderer().setSymbol(_marker("#32d5d2", 4.0, "#ffffff", 0.4))
    elif kind == "jshis":
        field = "T30_P03_SI"
        idx = layer.fields().indexOf(field)
        if idx >= 0:
            values = []
            for v in layer.uniqueValues(idx):
                try:
                    number = float(v)
                except (TypeError, ValueError):
                    number = None
                if number is not None:
                    values.append((number, v))
            values.sort()
            cats = []
            n = max(1, len(values) - 1)
            # QGIS interpolateColor API differs by version; use an explicit hazard palette.
            palette = ["#f5e7d8", "#f6b48b", "#f36f4a", "#e6333f", "#bd174c", "#8d205d", "#5f255d", "#351b45", "#12051f"]
            for i, (_number, raw) in enumerate(values):
                pos = i / n
                pidx = min(len(palette) - 1, int(round(pos * (len(palette) - 1))))
                sym = QgsFillSymbol.createSimple({"color": palette[pidx], "outline_color": "255,255,255,0", "outline_width": "0"})
                sym.setOpacity(0.80)
                cats.append(QgsRendererCategory(raw, sym, f"{float(raw):.1f}"))
            layer.setRenderer(QgsCategorizedSymbolRenderer(field, cats))
    layer.triggerRepaint()


def add_vector_to_group(path: Path, display_name: str, group_name: str, index: int, style_kind: str):
    remove_existing_layer_for_path(path)
    layer = QgsVectorLayer(str(path), display_name, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"作成済みFGBをQGISへ追加できません: {path}")
    style_vector(layer, style_kind)
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup(group_name) or root.addGroup(group_name)
    project.addMapLayer(layer, False)
    group.insertLayer(index, layer)
    return layer


def add_background_group():
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup("背景地図") or root.addGroup("背景地図")
    for index, (name, url, zmin, zmax, visible, opacity) in enumerate(BACKGROUND_TILES):
        # Recreate exact-name layers so a project containing a broken layer from an
        # earlier development build is repaired automatically.
        for old_layer in project.mapLayersByName(name):
            project.removeMapLayer(old_layer.id())
        # QGIS' WMS provider expects the XYZ URL template itself unescaped here.
        # Encoding the full URL prevents {z}/{x}/{y} substitution in QGIS 4.x.
        uri = f"type=xyz&url={url}&zmin={zmin}&zmax={zmax}"
        layer = QgsRasterLayer(uri, name, "wms")
        if not layer.isValid():
            raise RuntimeError(f"XYZタイルを追加できません: {name}")
        renderer = layer.renderer()
        if renderer is not None and hasattr(renderer, "setOpacity"):
            renderer.setOpacity(opacity)
        project.addMapLayer(layer, False)
        node = group.insertLayer(index, layer)
        node.setItemVisibilityChecked(visible)
    group.setItemVisibilityChecked(True)


def add_jshis_wms_fallback(pref_geometry: QgsGeometry):
    """Add J-SHIS WMS at 70% opacity and restrict rendering to the prefecture.

    This is a display-only fallback. The preferred path remains first-mesh vector
    download -> merge -> physical N03 polygon clip -> FGB. When the interactive
    J-SHIS download endpoint cannot be resolved, the WMS is clipped at render time
    so it is never shown nationwide for a prefecture-specific data pack.
    """
    project = QgsProject.instance()
    canonical = "確率論的地震動予測地図（30年超過確率3%・計測震度）_2024_J-SHIS"
    name = canonical + "（WMS代替）"

    # Remove a stale nationwide fallback so a rerun refreshes an existing project.
    for old_name in (canonical, name):
        for old_layer in list(project.mapLayersByName(old_name)):
            if old_layer.providerType() == "wms":
                project.removeMapLayer(old_layer.id())

    base_url = "https://www.j-shis.bosai.go.jp/map/wms/pshm/Y2024"
    layer_name = "P-Y2024-MAP-MAX-TTL_MTTL-T30_P03_SI"
    uri = (
        f"url={base_url}&layers={layer_name}&styles=&format=image/png"
        "&crs=EPSG:4326"
    )
    layer = QgsRasterLayer(uri, name, "wms")
    if not layer.isValid():
        raise RuntimeError("J-SHIS確率論的地震動WMSを追加できませんでした。")
    renderer = layer.renderer()
    if renderer is not None and hasattr(renderer, "setOpacity"):
        renderer.setOpacity(0.70)
    layer.setCustomProperty("gcham/jshis_wms_fallback", True)
    layer.setCustomProperty("gcham/jshis_wms_opacity", 0.70)
    layer.setCustomProperty("gcham/jshis_prefecture_clip", True)

    root = project.layerTreeRoot()
    group = root.findGroup("災害") or root.addGroup("災害")
    project.addMapLayer(layer, False)
    group.insertLayer(2, layer)

    # Map clipping regions use the destination map CRS. Restrict the clipping
    # effect to this WMS only, so background maps and other groups remain visible.
    try:
        from qgis.utils import iface
        canvas = iface.mapCanvas() if iface is not None else None
        if canvas is not None:
            clip_geom = QgsGeometry(pref_geometry)
            src_crs = QgsCoordinateReferenceSystem.fromEpsgId(GEOGRAPHIC_CRS_EPSG)
            dst_crs = canvas.mapSettings().destinationCrs()
            if dst_crs.isValid() and dst_crs != src_crs:
                transform = QgsCoordinateTransform(src_crs, dst_crs, project.transformContext())
                clip_geom.transform(transform)
            region = QgsMapClippingRegion(clip_geom)
            region.setRestrictToLayers(True)
            region.setRestrictedLayers([layer])
            settings = canvas.mapSettings()
            regions = list(settings.clippingRegions())
            regions.append(region)
            settings.setClippingRegions(regions)
            canvas.refresh()
            layer.setCustomProperty("gcham/jshis_canvas_clip_applied", True)
    except Exception as exc:
        # The WMS remains usable; the log caller will make the fallback explicit.
        layer.setCustomProperty("gcham/jshis_canvas_clip_error", str(exc))

    return layer


def move_root_group_after(group_name: str, after_group_name: str):
    """Move a top-level layer-tree group immediately after another group."""
    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(group_name)
    after = root.findGroup(after_group_name)
    if group is None or after is None or group is after:
        return
    if group.parent() is not root or after.parent() is not root:
        return
    children = root.children()
    after_index = children.index(after)
    current_index = children.index(group)
    if current_index == after_index + 1:
        return
    clone = group.clone()
    root.removeChildNode(group)
    after_index = root.children().index(after)
    root.insertChildNode(after_index + 1, clone)


@dataclass(frozen=True)
class SupplementalResult:
    path: Path
    display_name: str
    group: str
    style: str


class SupplementalBuilder:
    def __init__(
        self, output_dir: Path, pref_code: str, pref_name: str, target_epsg: int,
        municipalities: list[Municipality], reuse: bool = True,
        log: Callable[[str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.pref_code = pref_code
        self.pref_name = pref_name
        self.target_epsg = target_epsg
        self.municipalities = municipalities
        self.pref_geometry = _pref_union(municipalities)
        self.reuse = reuse
        self.log = log or (lambda _m: None)
        self.is_cancelled = is_cancelled or (lambda: False)
        self.cache = self.output_dir / "_cache" / "supplemental"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.output_dir / "supplemental"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def check_cancelled(self):
        if self.is_cancelled():
            raise CancelledError("処理がキャンセルされました。")

    def _download_zip(self, url: str, path: Path) -> Path:
        if self.reuse and valid_zip(path):
            self.log(f"キャッシュを再利用: {path.name}")
            return path
        download_file(url, path, log=self.log)
        if not valid_zip(path):
            raise RuntimeError(f"有効なZIPを取得できませんでした: {url}")
        return path

    def _request_bytes(
        self, url: str, method: str = "get", form_pairs: list[tuple[str, str]] | None = None
    ) -> tuple[bytes, dict[str, str]]:
        """Issue a blocking request through QGIS so proxy/SSL settings are respected."""
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(QByteArray(b"User-Agent"), QByteArray(b"QGIS G-CHAM Data Pack Builder"))
        blocking = QgsBlockingNetworkRequest()
        if method.lower() == "post":
            body = urlencode(form_pairs or [], doseq=True).encode("utf-8")
            request.setRawHeader(
                QByteArray(b"Content-Type"),
                QByteArray(b"application/x-www-form-urlencoded; charset=UTF-8"),
            )
            err = blocking.post(request, QByteArray(body), True)
        else:
            err = blocking.get(request, True)
        if err != _enum_member(QgsBlockingNetworkRequest, "ErrorCode", "NoError"):
            raise RuntimeError(f"J-SHIS通信失敗: {url}\n{blocking.errorMessage()}")
        reply = blocking.reply()
        content = bytes(reply.content())
        headers = {}
        for header_name in reply.rawHeaderList():
            key = bytes(header_name).decode("latin-1", errors="replace").lower()
            value = bytes(reply.rawHeader(header_name)).decode("latin-1", errors="replace")
            headers[key] = value
        return content, headers

    @staticmethod
    def _decode_web_text(content: bytes) -> str:
        for encoding in ("utf-8", "utf-8-sig", "cp932", "shift_jis", "euc_jp"):
            try:
                decoded = content.decode(encoding)
            except UnicodeDecodeError:
                decoded = None
            if decoded is not None:
                return decoded
        return content.decode("utf-8", errors="replace")

    def _jshis_download_document(self) -> tuple[str, str]:
        """Fetch the official page and same-origin scripts used to construct downloads."""
        cache = self.cache / "jshis" / "Y2024_MAX"
        cache.mkdir(parents=True, exist_ok=True)
        page_path = cache / "download_page.html"
        try:
            content, _headers = self._request_bytes(JSHIS_DOWNLOAD_PAGE)
            page_path.write_bytes(content)
        except RuntimeError:
            if not page_path.exists():
                raise
            content = page_path.read_bytes()
        page_html = self._decode_web_text(content)
        corpus = [page_html]
        script_urls = []
        for match in re.finditer(r"<script\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", page_html, re.I):
            script_url = urljoin(JSHIS_DOWNLOAD_PAGE, html.unescape(match.group(1)))
            if "j-shis.bosai.go.jp" not in script_url:
                continue
            if script_url not in script_urls:
                script_urls.append(script_url)
        for index, script_url in enumerate(script_urls[:20]):
            self.check_cancelled()
            script_path = cache / f"download_script_{index:02d}.js"
            try:
                script_content, _headers = self._request_bytes(script_url)
                script_path.write_bytes(script_content)
            except RuntimeError:
                if not script_path.exists():
                    continue
                script_content = script_path.read_bytes()
            corpus.append(self._decode_web_text(script_content))
        return page_html, "\n".join(corpus)

    def _save_jshis_zip_content(self, content: bytes, destination: Path) -> bool:
        if not _looks_like_zip(content):
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        part = destination.with_suffix(destination.suffix + ".part")
        part.write_bytes(content)
        if not valid_zip(part):
            part.unlink(missing_ok=True)
            return False
        part.replace(destination)
        return True

    def _try_jshis_zip_url(self, url: str, destination: Path) -> bool:
        try:
            content, _headers = self._request_bytes(url)
        except RuntimeError as exc:
            self.log(f"J-SHIS候補URL取得失敗: {exc}")
            return False
        return self._save_jshis_zip_content(content, destination)

    def _download_jshis_first_mesh_zip(
        self, mesh_code: str, page_html: str, corpus: str
    ) -> Path | None:
        """Automatically request one first-mesh PSHM Shapefile ZIP.

        J-SHIS exposes the first-mesh download through its interactive page rather than a
        separately documented archive API. The page is therefore inspected at runtime.
        This keeps the plugin independent of unstable CSS element ids and permits the
        official form/action or generated ZIP link to change without shipping source data.
        """
        cache = self.cache / "jshis" / "Y2024_MAX"
        destination = cache / f"P-Y2024-MAP-MAX-TTL_MTTL_{mesh_code}_SHP.zip"
        if self.reuse and valid_zip(destination):
            self.log(f"J-SHISキャッシュを再利用: 1次メッシュ {mesh_code}")
            return destination

        # Some site revisions embed generated/static archive links directly in HTML or JS.
        for url in _zip_urls_from_text(corpus, JSHIS_DOWNLOAD_PAGE, mesh_code):
            self.check_cancelled()
            if self._try_jshis_zip_url(url, destination):
                self.log(f"J-SHIS 1次メッシュ取得: {mesh_code}")
                return destination

        # Other revisions submit a conventional form. Reconstruct target settings by
        # matching semantic values (ZIP, Shapefile, first mesh, Y2024, TTL_MTTL, MAX).
        candidates = []
        for form in _jshis_forms(page_html):
            pairs, score = _jshis_form_payload(form, mesh_code)
            if score > 0:
                candidates.append((score, form, pairs))
        candidates.sort(key=lambda item: item[0], reverse=True)
        for score, form, pairs in candidates[:6]:
            self.check_cancelled()
            if score < 20:
                continue
            if not any(value == mesh_code or mesh_code in value for _name, value in pairs):
                mesh_names = []
                for item in form["inputs"]:
                    name = item.get("name", "")
                    ident = item.get("id", "")
                    if "mesh" in (name + " " + ident).lower():
                        mesh_names.append(name)
                if mesh_names:
                    pairs.append((mesh_names[0], mesh_code))
                else:
                    continue
            action = urljoin(JSHIS_DOWNLOAD_PAGE, form.get("action") or JSHIS_DOWNLOAD_PAGE)
            method = form.get("method", "get").lower()
            try:
                if method == "post":
                    content, _headers = self._request_bytes(action, "post", pairs)
                    response_base = action
                else:
                    query = urlencode(pairs, doseq=True)
                    separator = "&" if "?" in action else "?"
                    request_url = action + separator + query
                    content, _headers = self._request_bytes(request_url)
                    response_base = request_url
            except RuntimeError as exc:
                self.log(f"J-SHISフォーム送信失敗 ({mesh_code}): {exc}")
                continue
            if self._save_jshis_zip_content(content, destination):
                self.log(f"J-SHIS 1次メッシュ取得: {mesh_code}")
                return destination
            response_text = self._decode_web_text(content)
            for url in _zip_urls_from_text(response_text, response_base, mesh_code):
                if self._try_jshis_zip_url(url, destination):
                    self.log(f"J-SHIS 1次メッシュ取得: {mesh_code}")
                    return destination
        return None

    @staticmethod
    def _jshis_vectors_from_zip(zip_path: Path, extract: Path) -> list[Path]:
        if not extract.exists():
            safe_extract_zip(zip_path, extract)
        vectors = []
        for path in _source_vector_files(extract):
            layer = QgsVectorLayer(str(path), "jshis_check", "ogr")
            if layer.isValid() and layer.fields().indexOf("T30_P03_SI") >= 0:
                vectors.append(path)
        return vectors

    def _ksj_vectors(self, dataset: str, yy: str, filename: str, preferred: str | None = None) -> list[Path]:
        cache = self.cache / "ksj" / dataset
        zip_path = cache / filename
        url = f"{KSJ_BASE}/{dataset}/{dataset}-{yy}/{filename}"
        self._download_zip(url, zip_path)
        extract = cache / zip_path.stem
        if not (self.reuse and extract.exists()):
            if extract.exists():
                shutil.rmtree(extract)
            safe_extract_zip(zip_path, extract)
        return _source_vector_files(extract, preferred)

    def build_facilities(self) -> list[SupplementalResult]:
        results = []
        for dataset, yy, year, filename_tpl, title, out_tpl, style in FACILITY_SPECS:
            self.check_cancelled()
            filename = filename_tpl.format(pref=self.pref_code)
            vectors = self._ksj_vectors(dataset, yy, filename)
            out = self.data_dir / out_tpl.format(pref=self.pref_code)
            remove_existing_layer_for_path(out)
            out.unlink(missing_ok=True)
            _write_merged_vectors(vectors, out, self.target_epsg)
            results.append(SupplementalResult(out, f"{title}_{year}_国土数値情報", "施設", style))
        return results

    def build_transport(self) -> list[SupplementalResult]:
        results = []
        for dataset, yy, year, filename_tpl, title, out_tpl, style in TRANSPORT_PREF_SPECS:
            self.check_cancelled()
            filename = filename_tpl.format(pref=self.pref_code)
            vectors = self._ksj_vectors(dataset, yy, filename)
            out = self.data_dir / out_tpl.format(pref=self.pref_code)
            remove_existing_layer_for_path(out)
            out.unlink(missing_ok=True)
            _write_merged_vectors(vectors, out, self.target_epsg)
            results.append(SupplementalResult(out, f"{title}_{year}_国土数値情報", "交通", style))

        # N02 2025 is distributed nationwide; extract Station and RailroadSection once.
        n02 = self._ksj_vectors("N02", "25", "N02-25_GML.zip")
        station_sources = [p for p in n02 if "station" in p.stem.lower()]
        rail_sources = [p for p in n02 if "railroadsection" in p.stem.lower() or "railroad" in p.stem.lower() and "station" not in p.stem.lower()]
        if not station_sources or not rail_sources:
            # Search the extraction tree independently because _ksj_vectors may select all formats.
            cache = self.cache / "ksj" / "N02" / "N02-25_GML"
            all_vectors = _source_vector_files(cache)
            station_sources = [p for p in all_vectors if "station" in p.stem.lower()]
            rail_sources = [p for p in all_vectors if "railroadsection" in p.stem.lower() or ("railroad" in p.stem.lower() and "station" not in p.stem.lower())]
        if not station_sources or not rail_sources:
            raise RuntimeError("N02-2025からStation/RailroadSectionを識別できませんでした。")
        station_out = self.data_dir / f"n02_2025_{self.pref_code}_stations.fgb"
        rail_out = self.data_dir / f"n02_2025_{self.pref_code}_railway_lines.fgb"
        for out in (station_out, rail_out):
            remove_existing_layer_for_path(out)
            out.unlink(missing_ok=True)
        _write_merged_vectors(station_sources, station_out, self.target_epsg, self.pref_geometry)
        _write_merged_vectors(rail_sources, rail_out, self.target_epsg, self.pref_geometry)
        results.extend([
            SupplementalResult(station_out, "鉄道駅_2025_国土数値情報", "交通", "rail_station"),
            SupplementalResult(rail_out, "鉄道路線_2025_国土数値情報", "交通", "rail_line"),
        ])
        return results

    def build_roads(self) -> list[SupplementalResult]:
        results = []
        road_sources = []
        mesh_codes = first_mesh_codes(self.pref_geometry)
        self.log("道路N13対象メッシュ: " + ", ".join(mesh_codes))
        for code in mesh_codes:
            self.check_cancelled()
            road_sources.extend(self._ksj_vectors("N13", "24", f"N13-24_{code}_SHP.zip"))
        road_out = self.data_dir / f"n13_2024_{self.pref_code}_roads.fgb"
        remove_existing_layer_for_path(road_out)
        road_out.unlink(missing_ok=True)
        _write_merged_vectors(
            road_sources, road_out, self.target_epsg, self.pref_geometry, ROAD_MAPS,
            clip_to_pref=True,
        )
        results.append(SupplementalResult(road_out, "道路_2024_国土数値情報", "交通", "road"))
        return results

    @staticmethod
    def _decode_text(path: Path) -> str:
        data = path.read_bytes()
        for enc in ("utf-8", "utf-8-sig", "cp932"):
            try:
                decoded = data.decode(enc)
            except UnicodeDecodeError:
                decoded = None
            if decoded is not None:
                return decoded
        raise RuntimeError(f"文字コードを判定できません: {path.name}")

    @staticmethod
    def _same_origin_url(base_url: str, candidate: str) -> str | None:
        absolute = urljoin(base_url, html.unescape(candidate).replace("\\/", "/"))
        base = urlparse(base_url)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            return None
        if parsed.netloc != base.netloc:
            return None
        return absolute

    def _gsi_discovery_corpus(self, page_text: str, cache: Path) -> list[tuple[str, str]]:
        """Collect the public page plus same-origin JS/JSON assets used to populate it."""
        corpus: list[tuple[str, str]] = [(GSI_SHELTER_PAGE, page_text)]
        seen = {GSI_SHELTER_PAGE}

        # The public download table is currently JavaScript-populated. Follow only
        # same-origin script src and explicit JSON references; never crawl arbitrary links.
        candidates = re.findall(
            r'<script\b[^>]*\bsrc=["\']([^"\']+)["\']', page_text,
            flags=re.I,
        )
        candidates += re.findall(
            r'["\']([^"\']+\.json(?:\?[^"\']*)?)["\']', page_text,
            flags=re.I,
        )

        queue: list[str] = []
        for candidate in candidates:
            url = self._same_origin_url(GSI_SHELTER_PAGE, candidate)
            if url and url not in seen:
                queue.append(url)
                seen.add(url)

        # A small hard limit avoids accidental broad crawling if the site structure changes.
        index = 0
        while index < len(queue) and index < 20:
            self.check_cancelled()
            url = queue[index]
            suffix = Path(urlparse(url).path).suffix.lower() or ".txt"
            asset = cache / "discovery" / f"asset_{index:02d}{suffix}"
            try:
                if not (self.reuse and asset.exists()):
                    download_file(url, asset, log=None)
                content = self._decode_text(asset)
            except RuntimeError:
                index += 1
                continue
            corpus.append((url, content))

            # JS often stores the backing JSON endpoint as a quoted string.
            for candidate in re.findall(
                r'["\']([^"\']+\.json(?:\?[^"\']*)?)["\']', content,
                flags=re.I,
            ):
                json_url = self._same_origin_url(url, candidate)
                if not json_url or json_url in seen or len(queue) >= 20:
                    continue
                queue.append(json_url)
                seen.add(json_url)
            index += 1

        return corpus

    def _gsi_info(self) -> tuple[str, str, str]:
        cache = self.cache / "gsi"
        page = cache / "koukaidate.html"
        if not (self.reuse and page.exists()):
            download_file(GSI_SHELTER_PAGE, page, log=self.log)
        page_text = self._decode_text(page)
        corpus = self._gsi_discovery_corpus(page_text, cache)

        # Search the rendered-data sources as well as the static HTML. The selected
        # prefecture block must contain two CSV references: emergency site and shelter.
        for source_url, source_text in corpus:
            normalized = html.unescape(source_text).replace("\\/", "/")
            positions = [m.start() for m in re.finditer(re.escape(self.pref_name), normalized)]
            for pos in positions:
                block = normalized[max(0, pos - 5000): pos + 12000]
                hrefs = re.findall(
                    r'(?:https?://[^\s"\'<>]+|[^\s"\'<>]+)\.csv(?:\?[^\s"\'<>]*)?',
                    block, flags=re.I,
                )
                hrefs = [h.rstrip('),];') for h in hrefs]
                hrefs = list(dict.fromkeys(hrefs))
                if len(hrefs) < 2:
                    continue
                plain = html.unescape(re.sub(r"<[^>]+>", " ", block))
                dm = re.search(
                    r"(20\d{2})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})\s*日?",
                    plain,
                )
                if not dm:
                    continue
                date_str = f"{int(dm.group(1)):04d}{int(dm.group(2)):02d}{int(dm.group(3)):02d}"
                urls = [urljoin(source_url, href) for href in hrefs[:2]]
                self.log(f"GSI都道府県別CSVリンクを検出: {self.pref_name} / {date_str}")
                return date_str, urls[0], urls[1]

        raise RuntimeError(
            "公開ページと参照JS/JSONから指定緊急避難場所/指定避難所の都道府県CSVリンクを検出できません。"
        )

    @staticmethod
    def _csv_rows(path: Path):
        data = path.read_bytes()
        decoded = None
        for enc in ("cp932", "utf-8-sig", "utf-8"):
            try:
                decoded = data.decode(enc)
            except UnicodeDecodeError:
                decoded = None
            if decoded is not None:
                break
        if decoded is None:
            raise RuntimeError(f"CSV文字コードを判定できません: {path.name}")
        return list(csv.DictReader(decoded.splitlines()))

    def _gsi_csv_to_fgb(self, csv_path: Path, out: Path):
        rows = self._csv_rows(csv_path)
        if not rows:
            raise RuntimeError(f"CSVにデータがありません: {csv_path.name}")
        names = list(rows[0].keys())
        fields = QgsFields()
        for name in names:
            fields.append(QgsField(str(name), qmeta_string()))
        point_wkb = _enum_member(Qgis, "WkbType", "Point")
        writer = _create_writer(out, fields, point_wkb, self.target_epsg)
        source = QgsCoordinateReferenceSystem.fromEpsgId(GEOGRAPHIC_CRS_EPSG)
        transform = _transform(source, self.target_epsg)
        written = 0
        try:
            for row in rows:
                try:
                    lat = float(str(row.get("緯度", "")).strip())
                    lon = float(str(row.get("経度", "")).strip())
                except ValueError:
                    lat = lon = None
                if lat is None or lon is None:
                    continue
                feat = QgsFeature(fields)
                geom = QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
                if transform is not None:
                    geom.transform(transform)
                feat.setGeometry(geom)
                feat.setAttributes([row.get(name) for name in names])
                if not writer.addFeature(feat, _enum_member(QgsFeatureSink, "Flag", "FastInsert")):
                    raise RuntimeError(f"FGB書き込みに失敗しました: {out.name}")
                written += 1
        finally:
            del writer
            gc.collect()
        if not written:
            raise RuntimeError(f"有効な緯度経度を持つ地物がありません: {csv_path.name}")


    @staticmethod
    def _slippy_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
        lat = max(-85.05112878, min(85.05112878, lat))
        n = 2 ** zoom
        x = int((lon + 180.0) / 360.0 * n)
        lat_rad = math.radians(lat)
        y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        return max(0, min(n - 1, x)), max(0, min(n - 1, y))

    @staticmethod
    def _slippy_tile_geometry(x: int, y: int, zoom: int) -> QgsGeometry:
        n = 2 ** zoom
        west = x / n * 360.0 - 180.0
        east = (x + 1) / n * 360.0 - 180.0
        north = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
        south = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n))))
        ring = [
            QgsPointXY(west, south), QgsPointXY(east, south),
            QgsPointXY(east, north), QgsPointXY(west, north),
            QgsPointXY(west, south),
        ]
        return QgsGeometry.fromPolygonXY([ring])

    def _gsi_intersecting_tiles(self, zoom: int) -> list[tuple[int, int]]:
        bbox = self.pref_geometry.boundingBox()
        x0, y_south = self._slippy_tile(bbox.xMinimum(), bbox.yMinimum(), zoom)
        x1, y_north = self._slippy_tile(bbox.xMaximum(), bbox.yMaximum(), zoom)
        xmin, xmax = sorted((x0, x1))
        ymin, ymax = sorted((y_north, y_south))
        tiles = []
        for x in range(xmin, xmax + 1):
            for y in range(ymin, ymax + 1):
                if self._slippy_tile_geometry(x, y, zoom).intersects(self.pref_geometry):
                    tiles.append((x, y))
        return tiles

    def _gsi_tile_records(self, layers: list[str], emergency: bool) -> list[dict]:
        zoom = 10
        tiles = self._gsi_intersecting_tiles(zoom)
        cache = self.cache / "gsi" / "tiles"
        merged: dict[tuple, dict] = {}
        attempted = 0
        downloaded = 0
        empty_tiles = 0
        read_errors = 0

        for layer_id in layers:
            for x, y in tiles:
                self.check_cancelled()
                attempted += 1
                tile_path = cache / layer_id / str(zoom) / str(x) / f"{y}.geojson"
                url = f"https://cyberjapandata.gsi.go.jp/xyz/{layer_id}/{zoom}/{x}/{y}.geojson"
                if not (self.reuse and tile_path.exists()):
                    try:
                        download_file(url, tile_path, log=None)
                        downloaded += 1
                    except RuntimeError as exc:
                        # The official shelter layers are sparse. A 404 simply means that
                        # this thematic layer has no GeoJSON tile at the requested location.
                        if "Not Found" in str(exc) or "404" in str(exc):
                            empty_tiles += 1
                        else:
                            read_errors += 1
                        continue
                try:
                    obj = json.loads(tile_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    read_errors += 1
                    continue
                for feature in obj.get("features", []):
                    geom = feature.get("geometry") or {}
                    if geom.get("type") != "Point":
                        continue
                    coords = geom.get("coordinates") or []
                    if len(coords) < 2:
                        continue
                    try:
                        lon, lat = float(coords[0]), float(coords[1])
                    except (TypeError, ValueError):
                        lon = lat = None
                    if lon is None or lat is None:
                        continue
                    point = QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
                    if not point.intersects(self.pref_geometry):
                        continue
                    props = dict(feature.get("properties") or {})
                    key = (
                        round(lon, 7), round(lat, 7),
                        str(props.get("name", "")), str(props.get("address", "")),
                    )
                    if key not in merged:
                        merged[key] = {"lon": lon, "lat": lat, "properties": props}
                    else:
                        current = merged[key]["properties"]
                        for k, v in props.items():
                            if v not in (None, "", 0, False):
                                current[k] = v
                    if emergency and layer_id.startswith("skhb"):
                        try:
                            h = int(layer_id[-2:])
                        except ValueError:
                            h = 0
                        if 1 <= h <= 8:
                            merged[key]["properties"][f"disaster{h}"] = 1

        self.log(
            "GSI GeoJSONフォールバック: "
            f"県境交差タイル {len(tiles)}枚 × {len(layers)}レイヤ / "
            f"要求 {attempted} / 新規取得 {downloaded} / 空タイル {empty_tiles} / "
            f"その他失敗 {read_errors} / 採用地物 {len(merged)}件"
        )
        return list(merged.values())

    def _gsi_tile_records_to_fgb(self, records: list[dict], out: Path, emergency: bool):
        if not records:
            raise RuntimeError("国土地理院GeoJSONタイルから対象地物を取得できませんでした。")
        if emergency:
            field_map = [
                ("施設・場所名", "name"), ("住所", "address"),
                ("洪水", "disaster1"), ("崖崩れ、土石流及び地滑り", "disaster2"),
                ("高潮", "disaster3"), ("地震", "disaster4"), ("津波", "disaster5"),
                ("大規模な火事", "disaster6"), ("内水氾濫", "disaster7"),
                ("火山現象", "disaster8"), ("緯度", "__lat"), ("経度", "__lon"),
                ("備考", "remarks"),
            ]
        else:
            field_map = [
                ("施設・場所名", "name"), ("住所", "address"),
                ("その他市町村長が必要と認める事項", "necessary_matters"),
                ("受入対象者", "accept"), ("緯度", "__lat"), ("経度", "__lon"),
                ("備考", "remarks"),
            ]
        fields = QgsFields()
        for name, _source in field_map:
            fields.append(QgsField(name, qmeta_string()))
        point_wkb = _enum_member(Qgis, "WkbType", "Point")
        writer = _create_writer(out, fields, point_wkb, self.target_epsg)
        transform = _transform(QgsCoordinateReferenceSystem.fromEpsgId(GEOGRAPHIC_CRS_EPSG), self.target_epsg)
        try:
            for record in records:
                props = record["properties"]
                lon, lat = record["lon"], record["lat"]
                feat = QgsFeature(fields)
                geom = QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
                if transform is not None:
                    geom.transform(transform)
                feat.setGeometry(geom)
                attrs = []
                for _name, source in field_map:
                    if source == "__lat":
                        attrs.append(str(lat))
                    elif source == "__lon":
                        attrs.append(str(lon))
                    else:
                        value = props.get(source)
                        attrs.append("" if value is None else str(value))
                feat.setAttributes(attrs)
                if not writer.addFeature(feat, _enum_member(QgsFeatureSink, "Flag", "FastInsert")):
                    raise RuntimeError(f"FGB書き込みに失敗しました: {out.name}")
        finally:
            del writer
            gc.collect()

    def _jshis_first_mesh_vectors(self) -> tuple[list[Path], list[str]]:
        """Get only J-SHIS first-mesh archives intersecting the selected prefecture."""
        mesh_codes = first_mesh_codes(self.pref_geometry)
        self.log("J-SHIS対象1次メッシュ: " + ", ".join(mesh_codes))
        cache = self.cache / "jshis" / "Y2024_MAX"
        cache.mkdir(parents=True, exist_ok=True)

        try:
            page_html, corpus = self._jshis_download_document()
        except RuntimeError as exc:
            self.log(f"J-SHIS公式ダウンロード画面の解析に失敗しました: {exc}")
            page_html, corpus = "", ""

        vectors: list[Path] = []
        missing: list[str] = []
        for mesh_code in mesh_codes:
            self.check_cancelled()
            matched: list[Path] = []

            # Reuse either plugin-downloaded or manually cached official ZIPs.
            for zip_path in sorted(cache.glob(f"*{mesh_code}*.zip")):
                if not valid_zip(zip_path):
                    continue
                matched.extend(
                    self._jshis_vectors_from_zip(zip_path, cache / zip_path.stem)
                )

            if not matched and page_html:
                zip_path = self._download_jshis_first_mesh_zip(
                    mesh_code, page_html, corpus
                )
                if zip_path is not None:
                    matched.extend(
                        self._jshis_vectors_from_zip(zip_path, cache / zip_path.stem)
                    )

            if matched:
                vectors.extend(matched)
            else:
                missing.append(mesh_code)

        # Preserve deterministic order and avoid duplicate paths from overlapping caches.
        vectors = list(dict.fromkeys(vectors))
        return vectors, missing

    def build_disaster(self) -> list[SupplementalResult]:
        results = []
        # GSI designated emergency evacuation sites + designated shelters.
        # Prefer the prefecture CSV/download-page metadata. The public table is
        # currently populated dynamically, so use official GSI GeoJSON tiles as
        # a fully automatic fallback when direct CSV links cannot be discovered.
        try:
            gsi_date, emergency_url, shelter_url = self._gsi_info()
            gsi_cache = self.cache / "gsi" / self.pref_code
            emergency_csv = gsi_cache / f"emergency_{gsi_date}.csv"
            shelter_csv = gsi_cache / f"shelter_{gsi_date}.csv"
            if not (self.reuse and emergency_csv.exists()):
                download_file(emergency_url, emergency_csv, log=self.log)
            if not (self.reuse and shelter_csv.exists()):
                download_file(shelter_url, shelter_csv, log=self.log)
            emergency_out = self.data_dir / f"gsi_emergency_evacuation_{gsi_date}_{self.pref_code}.fgb"
            shelter_out = self.data_dir / f"gsi_designated_shelter_{gsi_date}_{self.pref_code}.fgb"
            for out in (emergency_out, shelter_out):
                remove_existing_layer_for_path(out)
                out.unlink(missing_ok=True)
            self._gsi_csv_to_fgb(emergency_csv, emergency_out)
            self._gsi_csv_to_fgb(shelter_csv, shelter_out)
        except Exception as exc:
            gsi_date = date.today().strftime("%Y%m%d")
            self.log(
                "GSI都道府県別CSVを公開ページから解決できなかったため、公式GeoJSONタイルへフォールバックします。"
                f" レイヤ日付は取得日 {gsi_date} を使用します。詳細: {exc}"
            )
            emergency_out = self.data_dir / f"gsi_emergency_evacuation_{gsi_date}_{self.pref_code}.fgb"
            shelter_out = self.data_dir / f"gsi_designated_shelter_{gsi_date}_{self.pref_code}.fgb"
            for out in (emergency_out, shelter_out):
                remove_existing_layer_for_path(out)
                out.unlink(missing_ok=True)
            emergency_records = self._gsi_tile_records([f"skhb{i:02d}" for i in range(1, 9)], True)
            shelter_records = self._gsi_tile_records(["sih", "sfh"], False)
            self._gsi_tile_records_to_fgb(emergency_records, emergency_out, True)
            self._gsi_tile_records_to_fgb(shelter_records, shelter_out, False)
        results.extend([
            SupplementalResult(emergency_out, f"指定緊急避難場所_{gsi_date}_国土地理院", "災害", "gsi_emergency"),
            SupplementalResult(shelter_out, f"指定避難所_{gsi_date}_国土地理院", "災害", "gsi_shelter"),
        ])

        # J-SHIS probabilistic seismic hazard map. Download only the first-level
        # regional meshes intersecting the selected prefecture, merge them, then
        # physically clip the polygons to the N03 prefecture geometry.
        j_vectors, missing = self._jshis_first_mesh_vectors()
        if missing:
            cache = self.cache / "jshis" / "Y2024_MAX"
            self.log(
                "J-SHIS 1次メッシュの自動取得が完了しなかったため、WMSへフォールバックします。"
                "不足メッシュ: " + ", ".join(missing) +
                f"。公式ZIPを手動取得した場合は {cache} に置くと次回再利用します。"
            )
        if j_vectors and not missing:
            j_out = self.data_dir / f"jshis_pshm_t30_p03_si_2024_{self.pref_code}.fgb"
            remove_existing_layer_for_path(j_out)
            j_out.unlink(missing_ok=True)
            _write_merged_vectors(
                j_vectors, j_out, self.target_epsg, self.pref_geometry,
                clip_to_pref=True,
            )
            check = QgsVectorLayer(str(j_out), "jshis_output_check", "ogr")
            if not check.isValid() or check.fields().indexOf("T30_P03_SI") < 0:
                j_out.unlink(missing_ok=True)
                raise RuntimeError("J-SHIS出力FGBにT30_P03_SIを確認できませんでした。")
            results.append(SupplementalResult(
                j_out, "確率論的地震動予測地図（30年超過確率3%・計測震度）_2024_J-SHIS", "災害", "jshis"
            ))
        return results

    def add_results(self, results: list[SupplementalResult]):
        counters: dict[str, int] = {}
        for result in results:
            index = counters.get(result.group, 0)
            add_vector_to_group(result.path, result.display_name, result.group, index, result.style)
            counters[result.group] = index + 1

    def safe_build(self, method_name: str) -> list[SupplementalResult]:
        try:
            return getattr(self, method_name)()
        except CancelledError:
            raise
        except Exception as exc:
            self.log(f"追加データ警告 [{method_name}]: {exc}")
            return []
