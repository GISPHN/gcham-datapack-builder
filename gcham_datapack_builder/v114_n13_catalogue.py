# SPDX-License-Identifier: GPL-2.0-or-later
"""Cross-check candidate N13 first meshes with the official 2024 distribution."""
from __future__ import annotations
import re
from pathlib import Path
from . import supplemental, v113_roadfix
from . import qgis_io
import gc
from qgis.core import QgsVectorLayer, QgsFeature, QgsVectorFileWriter, QgsWkbTypes, QgsProject, Qgis

# Deliberately conservative screening, not proof of legal walking/cycling access.
_ALLOWED_CLASSES = {1, 2, 3, 5}

def _code(value):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None

def _walk_cycle_candidate(feature):
    return (
        _code(feature['N13_003']) in _ALLOWED_CLASSES
        and _code(feature['N13_007']) == 1
    )

def _create_walk_cycle_fgb(source_path, dest_path, log, check_cancelled):
    source = QgsVectorLayer(str(source_path), 'n13_original', 'ogr')
    if not source.isValid():
        raise RuntimeError('道路元FGBが読み込めません: ' + str(source_path))
    needed = ('N13_003', 'N13_007')
    missing = [name for name in needed if source.fields().indexOf(name) < 0]
    if missing:
        raise RuntimeError('徒歩・自転車用道路の抽出に必要な列がありません: ' + ', '.join(missing))
    qgis_io.remove_existing_layer_for_path(dest_path)
    dest_path.unlink(missing_ok=True)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'FlatGeobuf'
    options.fileEncoding = 'UTF-8'
    options.layerName = dest_path.stem
    options.layerOptions = ['SPATIAL_INDEX=YES']
    options.actionOnExistingFile = getattr(
        getattr(QgsVectorFileWriter, 'ActionOnExistingFile', QgsVectorFileWriter),
        'CreateOrOverwriteFile'
    )
    writer = QgsVectorFileWriter.create(
        str(dest_path), source.fields(), source.wkbType(), source.crs(),
        QgsProject.instance().transformContext(), options
    )
    no_error = getattr(getattr(QgsVectorFileWriter, 'WriterError', QgsVectorFileWriter), 'NoError')
    if writer is None or writer.hasError() != no_error:
        msg = writer.errorMessage() if writer is not None else 'writer is None'
        raise RuntimeError('道路抽出FGBの生成に失敗: ' + msg)
    seen = kept = 0
    failure = False
    try:
        for feature in source.getFeatures():
            seen += 1
            if seen % 2500 == 0:
                check_cancelled()
            if not _walk_cycle_candidate(feature):
                continue
            if not writer.addFeature(feature):
                raise RuntimeError('徒歩・自転車解析用道路FGBへの書き込みに失敗')
            kept += 1
    except Exception:
        failure = True
        raise
    finally:
        del writer
        gc.collect()
        if failure:
            dest_path.unlink(missing_ok=True)
    if kept == 0:
        dest_path.unlink(missing_ok=True)
        raise RuntimeError('徒歩・自転車解析用道路の抽出結果が0件です')
    log(f'徒歩・自転車解析用N13道路: 元{seen:,}件 / 抽出{kept:,}件 / 除外{seen-kept:,}件')
    return dest_path

def _set_road_visibility():
    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup('交通')
    if group is None:
        return
    for node in group.findLayers():
        layer = node.layer()
        if layer is None:
            continue
        if layer.name() == '道路_2024_国土数値情報':
            node.setItemVisibilityChecked(False)
        elif layer.name() == '道路_徒歩・自転車解析用（高速・有料除外）_2024_国土数値情報':
            node.setItemVisibilityChecked(True)

def _patch_add_results():
    original = supplemental.SupplementalBuilder.add_results
    if getattr(original, '_gcham_walk_cycle_visibility', False):
        return
    def add_results(self, results):
        original(self, results)
        if any(r.display_name == '道路_徒歩・自転車解析用（高速・有料除外）_2024_国土数値情報' for r in results):
            _set_road_visibility()
    add_results._gcham_walk_cycle_visibility = True
    supplemental.SupplementalBuilder.add_results = add_results

_APPLIED = False
OFFICIAL_N13_PAGE = 'https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N13-2024.html'
N13_ARCHIVE_PATTERN = re.compile(r'N13-24_([0-9]{4})_SHP\.zip', re.IGNORECASE)

def _published_n13_meshes(builder):
    cache = builder.cache / 'ksj' / 'N13' / 'N13-2024-published-meshes.html'
    # Always revalidate the public catalogue on each run, rather than silently
    # trusting a stale manifest. Do not fall back to skip-on-404 on failures.
    qgis_io.download_file(OFFICIAL_N13_PAGE, cache, log=None)
    page = cache.read_text(encoding='utf-8', errors='replace')
    codes = set(N13_ARCHIVE_PATTERN.findall(page))
    if len(codes) < 20:
        raise RuntimeError('N13-2024公式公開メッシュ一覧を取得できません。道路の取得を中断します。')
    return codes

def apply_v114_n13_catalogue():
    global _APPLIED
    if _APPLIED:
        return
    # Use the already optimized bbox-based merge writer from v1.1.3.
    def build_roads(self):
        candidates = supplemental.first_mesh_codes(self.pref_geometry)
        available = _published_n13_meshes(self)
        selected = [code for code in candidates if code in available]
        unavailable = [code for code in candidates if code not in available]
        self.log('道路N13候補メッシュ: ' + ', '.join(candidates))
        self.log('道路N13公式一覧で未提供のため除外: ' + (', '.join(unavailable) if unavailable else 'なし'))
        self.log(f'道路N13公式公開メッシュ {len(selected)}件 / 候補{len(candidates)}件')
        if not selected:
            self.log('道路N13: 対象区域に公式提供メッシュはありません。')
            return []
        paths=[]
        for code in selected:
            self.check_cancelled()
            # An error on a listed ZIP is a real download failure, never a skip.
            paths.extend(self._ksj_vectors('N13','24',f'N13-24_{code}_SHP.zip'))
        out = self.data_dir / f'n13_2024_{self.pref_code}_roads.fgb'
        qgis_io.remove_existing_layer_for_path(out)
        out.unlink(missing_ok=True)
        v113_roadfix._write_roads_fast(paths, out, self.target_epsg, self.pref_geometry, self.log, self.check_cancelled)
        walk_out = self.data_dir / f'n13_2024_{self.pref_code}_walk_cycle_candidate.fgb'
        _create_walk_cycle_fgb(out, walk_out, self.log, self.check_cancelled)
        return [
            supplemental.SupplementalResult(out, '道路_2024_国土数値情報', '交通', 'road'),
            supplemental.SupplementalResult(walk_out, '道路_徒歩・自転車解析用（高速・有料除外）_2024_国土数値情報', '交通', 'road'),
        ]
    supplemental.SupplementalBuilder.build_roads = build_roads
    _patch_add_results()
    _APPLIED = True
