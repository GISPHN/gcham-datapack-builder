# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Ryo Horiike / GISPHN

from __future__ import annotations

import sqlite3
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsFeature, QgsFeatureSink, QgsFields, QgsField

from .constants import (
    BASE_STATS_ID,
    COMMON_FIELDS,
    DERIVED_SPECS,
    ESTAT_URL,
    N03_URL,
    STAT_TABLES,
    MULTI_ZONE_PREFS,
    plane_rectangular_epsg,
)
from .core_logic import (
    ColumnDef,
    ascii_admin_filename,
    ascii_population_filename,
    ascii_pref_population_filename,
    estat_archive_name,
    iter_estat_rows,
    load_preset_config,
    make_unique_labels,
    n03_archive_name,
    parse_stat_value,
    read_estat_header,
    safe_ratio,
    split_gassan,
)
from .qgis_io import (
    CancelledError,
    Municipality,
    MunicipalityIndex,
    add_layer_to_group,
    close_writers,
    create_fgb_writer,
    download_file,
    find_n03_vector,
    geometry_transformer,
    load_and_dissolve_n03,
    merged_mesh_geometry,
    transform_geometry,
    qmeta_double,
    qmeta_int64,
    qmeta_string,
    remove_existing_layer_for_path,
    safe_extract_zip,
    valid_zip,
    write_admin_fgb,
)


@dataclass
class BuildOptions:
    pref_code: str
    pref_name: str
    output_dir: Path
    all_municipalities: bool
    selected_municipality_codes: set[str]
    use_preset: bool
    additional_codes: set[str]
    reuse_downloads: bool = True


class DataPackProcessor:
    def __init__(
        self,
        plugin_dir: Path,
        log: Callable[[str], None] | None = None,
        progress: Callable[[int, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ):
        self.plugin_dir = Path(plugin_dir)
        self.log_cb = log or (lambda _msg: None)
        self.progress_cb = progress or (lambda _pct, _msg: None)
        self.is_cancelled_cb = is_cancelled or (lambda: False)
        self.preset = load_preset_config(self.plugin_dir)

    def log(self, message: str):
        self.log_cb(message)
        QCoreApplication.processEvents()

    def progress(self, pct: int, message: str):
        self.progress_cb(max(0, min(100, pct)), message)
        QCoreApplication.processEvents()
        self.check_cancelled()

    def check_cancelled(self):
        if self.is_cancelled_cb():
            raise CancelledError("処理がキャンセルされました。")

    def _cache_dir(self, output_dir: Path) -> Path:
        path = output_dir / "_cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_estat_archives(self, pref_code: str, output_dir: Path, reuse: bool = True) -> dict[str, Path]:
        cache = self._cache_dir(output_dir) / "estat" / pref_code
        cache.mkdir(parents=True, exist_ok=True)
        result = {}
        for idx, (stats_id, table_name) in enumerate(STAT_TABLES, start=1):
            self.check_cancelled()
            path = cache / estat_archive_name(stats_id, pref_code)
            if reuse and valid_zip(path):
                try:
                    read_estat_header(path, stats_id)
                    self.log(f"e-Statキャッシュを再利用: {path.name}")
                    result[stats_id] = path
                    continue
                except Exception:
                    self.log(f"e-Statキャッシュが不正なため再取得: {path.name}")
            self.progress(2 + idx * 3, f"e-Stat取得: {table_name}")
            url = ESTAT_URL.format(stats_id=stats_id, pref_code=pref_code)
            download_file(url, path, log=self.log)
            if not valid_zip(path):
                raise RuntimeError(f"e-Statから有効なZIPを取得できませんでした: {path.name}")
            read_estat_header(path, stats_id)
            result[stats_id] = path
        return result

    def ensure_n03(self, pref_code: str, output_dir: Path, reuse: bool = True) -> Path:
        cache = self._cache_dir(output_dir) / "n03"
        cache.mkdir(parents=True, exist_ok=True)
        zip_path = cache / n03_archive_name(pref_code)
        if not (reuse and valid_zip(zip_path)):
            self.progress(3, "国土数値情報 N03 を取得しています")
            url = N03_URL.format(pref_code=pref_code)
            download_file(url, zip_path, log=self.log)
            if not valid_zip(zip_path):
                raise RuntimeError("国土数値情報から有効なN03 ZIPを取得できませんでした。")
        else:
            self.log(f"N03キャッシュを再利用: {zip_path.name}")

        extract_dir = cache / zip_path.stem
        if not reuse or not extract_dir.exists():
            if extract_dir.exists():
                import shutil
                shutil.rmtree(extract_dir)
            safe_extract_zip(zip_path, extract_dir)
        try:
            return find_n03_vector(extract_dir)
        except RuntimeError:
            # Cached extraction can be incomplete after an interrupted run.
            import shutil
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            safe_extract_zip(zip_path, extract_dir)
            return find_n03_vector(extract_dir)

    def prepare_municipalities(self, pref_code: str, output_dir: Path, reuse: bool = True) -> list[Municipality]:
        vector_path = self.ensure_n03(pref_code, output_dir, reuse)
        municipalities, _ = load_and_dissolve_n03(vector_path)
        return municipalities

    def prepare_headers(self, pref_code: str, output_dir: Path, reuse: bool = True):
        archives = self.ensure_estat_archives(pref_code, output_dir, reuse)
        return {sid: read_estat_header(path, sid) for sid, path in archives.items()}

    def selected_columns(self, headers, use_preset: bool, additional_codes: set[str]):
        by_code: dict[str, ColumnDef] = {}
        header_order: list[str] = []
        for stats_id, _ in STAT_TABLES:
            header = headers[stats_id]
            for col in header.columns():
                by_code[col.code] = col
                header_order.append(col.code)

        selected: list[ColumnDef] = []
        seen = set()
        if use_preset:
            for item in self.preset["fields"]:
                code = item["code"]
                if code not in by_code:
                    raise RuntimeError(f"G-CHAM既定項目がe-Statに見つかりません: {code}")
                if code not in seen:
                    selected.append(by_code[code])
                    seen.add(code)
        for code in header_order:
            if code in additional_codes and code not in seen:
                selected.append(by_code[code])
                seen.add(code)
        unknown = additional_codes - set(by_code)
        if unknown:
            raise RuntimeError("e-Statに存在しない追加項目があります: " + ", ".join(sorted(unknown)))
        return selected

    @staticmethod
    def _sql_ident(name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def _load_sqlite(self, archives: dict[str, Path], selected: list[ColumnDef], tmp_db: Path):
        selected_by_table: dict[str, list[str]] = defaultdict(list)
        for col in selected:
            selected_by_table[col.stats_id].append(col.code)

        conn = sqlite3.connect(tmp_db)
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        type_map: dict[str, str] = {col.code: "int" for col in selected}

        for table_idx, (stats_id, table_name) in enumerate(STAT_TABLES):
            self.check_cancelled()
            table = f"s_{stats_id}"
            codes = selected_by_table.get(stats_id, [])
            col_sql = ", ".join(f'{self._sql_ident(c)} NUMERIC' for c in codes)
            suffix = f", {col_sql}" if col_sql else ""
            conn.execute(
                f'CREATE TABLE {table} ('
                'KEY_CODE TEXT PRIMARY KEY, HTKSYORI INTEGER, HTKSAKI TEXT, GASSAN TEXT'
                f'{suffix})'
            )
            placeholders = ",".join("?" for _ in range(4 + len(codes)))
            insert_sql = f"INSERT OR REPLACE INTO {table} VALUES ({placeholders})"
            batch = []
            count = 0
            for row in iter_estat_rows(archives[stats_id]):
                count += 1
                htk = parse_stat_value(row.get("HTKSYORI"))
                if not isinstance(htk, int):
                    htk = 0
                values = []
                for code in codes:
                    value = parse_stat_value(row.get(code))
                    if isinstance(value, str):
                        type_map[code] = "string"
                    elif isinstance(value, float) and type_map.get(code) != "string":
                        type_map[code] = "double"
                    values.append(value)

                gassan_codes = sorted(split_gassan(row.get("GASSAN")))
                gassan_value = ";".join(gassan_codes) if gassan_codes else None
                htksaki_value = (str(row.get("HTKSAKI")).strip() if row.get("HTKSAKI") else None)
                batch.append((row.get("KEY_CODE"), htk, htksaki_value, gassan_value, *values))
                if len(batch) >= 5000:
                    conn.executemany(insert_sql, batch)
                    batch.clear()
                    if count % 20000 == 0:
                        QCoreApplication.processEvents()
                        self.check_cancelled()
            if batch:
                conn.executemany(insert_sql, batch)
            conn.execute(f"CREATE INDEX idx_{table}_htk ON {table}(HTKSYORI)")
            conn.commit()
            self.log(f"読み込み: {table_name} {count:,}行")
            self.progress(30 + table_idx * 4, f"6表を結合準備中 ({table_idx + 1}/6)")

        self._validate_suppression(conn)
        return conn, type_map, selected_by_table

    def _validate_suppression(self, conn: sqlite3.Connection):
        base = f"s_{BASE_STATS_ID}"
        for stats_id, table_name in STAT_TABLES:
            if stats_id == BASE_STATS_ID:
                continue
            table = f"s_{stats_id}"
            sql = f"""
                SELECT b.KEY_CODE,
                       b.HTKSYORI, x.HTKSYORI,
                       b.HTKSAKI, x.HTKSAKI,
                       b.GASSAN, x.GASSAN
                FROM {base} b JOIN {table} x USING(KEY_CODE)
                WHERE COALESCE(b.HTKSYORI,0) <> COALESCE(x.HTKSYORI,0)
                   OR COALESCE(b.HTKSAKI,'') <> COALESCE(x.HTKSAKI,'')
                   OR COALESCE(b.GASSAN,'') <> COALESCE(x.GASSAN,'')
                LIMIT 1
            """
            row = conn.execute(sql).fetchone()
            if row:
                raise RuntimeError(
                    "e-Statの秘匿・合算情報が6表間で一致しません。誤集計を防ぐため処理を停止しました。\n"
                    f"表: {table_name}\nKEY_CODE: {row[0]}\n"
                    "この組合せは自動統合せず、表別の秘匿仕様を確認する必要があります。"
                )
        self.log("秘匿情報の整合性確認: 6表で一致")

    def _joined_select(self, selected: list[ColumnDef], selected_by_table: dict[str, list[str]]):
        aliases = {sid: f"t{i}" for i, (sid, _) in enumerate(STAT_TABLES)}
        base_alias = aliases[BASE_STATS_ID]
        parts = [
            f"{base_alias}.KEY_CODE",
            f"{base_alias}.HTKSYORI",
            f"{base_alias}.HTKSAKI",
            f"{base_alias}.GASSAN",
        ]
        for col in selected:
            parts.append(f'{aliases[col.stats_id]}.{self._sql_ident(col.code)} AS {self._sql_ident(col.code)}')
        joins = []
        for sid, _ in STAT_TABLES:
            if sid == BASE_STATS_ID:
                continue
            joins.append(
                f"LEFT JOIN s_{sid} {aliases[sid]} ON {aliases[sid]}.KEY_CODE={base_alias}.KEY_CODE"
            )
        sql = (
            "SELECT " + ", ".join(parts) + f" FROM s_{BASE_STATS_ID} {base_alias} "
            + " ".join(joins)
        )
        return sql

    @staticmethod
    def _is_additive_label(label: str) -> bool:
        nonadditive = (
            "割合", "比率", "率（", "平均", "１人当たり", "1人当たり",
            "１世帯当たり", "1世帯当たり", "指数", "中央値",
        )
        return not any(token in label for token in nonadditive)

    def _build_population_fields(self, selected: list[ColumnDef], type_map: dict[str, str], use_preset: bool):
        fields = QgsFields()
        fields.append(QgsField("KEY_CODE", qmeta_string()))
        fields.append(QgsField("HTKSYORI", qmeta_int64()))
        fields.append(QgsField("HTKSAKI", qmeta_string()))
        fields.append(QgsField("GASSAN", qmeta_string()))
        labels = make_unique_labels(selected)
        for col in selected:
            kind = type_map.get(col.code, "double")
            qtype = qmeta_string() if kind == "string" else qmeta_double() if kind == "double" else qmeta_int64()
            fields.append(QgsField(labels[col.code], qtype))
        if use_preset:
            for item in self.preset["derived_fields"]:
                label = item["label"]
                fields.append(QgsField(label, qmeta_double()))
        return fields, labels

    def build(
        self,
        options: BuildOptions,
        confirm_existing: Callable[[list[Path]], str] | None = None,
    ) -> dict:
        out = options.output_dir
        out.mkdir(parents=True, exist_ok=True)
        admin_dir = out / "admin"
        pop_dir = out / "population"
        admin_dir.mkdir(exist_ok=True)
        pop_dir.mkdir(exist_ok=True)

        target_epsg = plane_rectangular_epsg(options.pref_code)
        transformer = geometry_transformer(target_epsg)
        self.log(f"出力CRS: EPSG:{target_epsg}（JGD2011 平面直角座標系）")
        if options.pref_code in MULTI_ZONE_PREFS:
            self.log(
                "注意: この都道府県は国土地理院の平面直角座標系で複数の系にまたがります。"
                f"初期版では主要区域の EPSG:{target_epsg} を都道府県共通CRSとして使用します。"
            )

        self.progress(1, "入力データを準備しています")
        n03_vector = self.ensure_n03(options.pref_code, out, options.reuse_downloads)
        municipalities, n03_fields = load_and_dissolve_n03(n03_vector)
        muni_by_code = {m.code: m for m in municipalities}
        if options.all_municipalities:
            target_codes = [m.code for m in municipalities]
        else:
            target_codes = sorted(options.selected_municipality_codes)
            missing = [c for c in target_codes if c not in muni_by_code]
            if missing:
                raise RuntimeError("N03に存在しない自治体コード: " + ", ".join(missing))
            if not target_codes:
                raise RuntimeError("自治体が選択されていません。")

        archives = self.ensure_estat_archives(options.pref_code, out, options.reuse_downloads)
        headers = {sid: read_estat_header(path, sid) for sid, path in archives.items()}
        selected = self.selected_columns(headers, options.use_preset, options.additional_codes)
        if not selected and not options.use_preset:
            self.log("統計項目は追加選択されていません。共通4列のみ出力します。")

        pref_pop = pop_dir / ascii_pref_population_filename(options.pref_code)
        admin_paths = {c: admin_dir / ascii_admin_filename(c) for c in target_codes}
        muni_pop_paths = {c: pop_dir / ascii_population_filename(c) for c in target_codes}
        all_targets = [pref_pop] + [admin_paths[c] for c in target_codes] + [muni_pop_paths[c] for c in target_codes]
        existing = [p for p in all_targets if p.exists()]
        mode = "overwrite"
        if existing and confirm_existing:
            mode = confirm_existing(existing)
            if mode == "cancel":
                raise CancelledError("既存ファイルの確認で処理を中止しました。")
        if mode not in {"overwrite", "skip"}:
            mode = "overwrite"

        if mode == "overwrite":
            for p in existing:
                remove_existing_layer_for_path(p)
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass

        self.progress(25, "行政区域FGBを作成しています")
        for i, code in enumerate(target_codes):
            self.check_cancelled()
            path = admin_paths[code]
            if not (mode == "skip" and path.exists()):
                write_admin_fgb(path, muni_by_code[code], n03_fields, target_epsg, transformer)
            if i % 10 == 0:
                QCoreApplication.processEvents()

        with tempfile.TemporaryDirectory(prefix="gcham_dpb_") as td:
            db_path = Path(td) / "join.sqlite"
            self.progress(32, "e-Stat 6表を読み込んでいます")
            conn, type_map, selected_by_table = self._load_sqlite(archives, selected, db_path)
            fields, labels = self._build_population_fields(selected, type_map, options.use_preset)
            index = MunicipalityIndex(municipalities)

            writers = {}
            pref_writer = None
            emitted = 0
            skipped_suppressed = 0
            unmatched_muni = 0
            cross_muni = 0
            try:
                if not (mode == "skip" and pref_pop.exists()):
                    pref_writer = create_fgb_writer(pref_pop, fields, target_epsg)
                for code in target_codes:
                    path = muni_pop_paths[code]
                    if mode == "skip" and path.exists():
                        continue
                    writers[code] = create_fgb_writer(path, fields, target_epsg)

                join_sql = self._joined_select(selected, selected_by_table)
                conn.row_factory = sqlite3.Row
                query = conn.execute(join_sql + " ORDER BY t0.KEY_CODE")
                fetch_one_sql = join_sql + " WHERE t0.KEY_CODE=?"
                value_codes = [c.code for c in selected]
                additive_codes = {c.code for c in selected if self._is_additive_label(c.label)}
                nonadditive = [c.label for c in selected if c.code not in additive_codes]
                if nonadditive:
                    self.log(
                        "注: 比率・平均等の非加算項目は秘匿元メッシュの値を加算せず、合算先の公表値を保持します。"
                    )

                total = conn.execute(f"SELECT COUNT(*) FROM s_{BASE_STATS_ID}").fetchone()[0]

                for row_no, row in enumerate(query, start=1):
                    if row_no % 1000 == 0:
                        self.check_cancelled()
                        QCoreApplication.processEvents()
                        pct = 55 + int(35 * row_no / max(total, 1))
                        self.progress(pct, f"250mメッシュを生成中 {row_no:,}/{total:,}")

                    key = str(row["KEY_CODE"])
                    htk = int(row["HTKSYORI"] or 0)
                    if htk == 2:
                        skipped_suppressed += 1
                        continue
                    gassan = split_gassan(row["GASSAN"])
                    values = {code: row[code] for code in value_codes}

                    if gassan:
                        for source_key in gassan:
                            source = conn.execute(fetch_one_sql, (source_key,)).fetchone()
                            if source is None:
                                raise RuntimeError(
                                    f"GASSANに記載されたKEY_CODEが基準表にありません: {source_key}"
                                )
                            for code in additive_codes:
                                v = source[code]
                                if v is None:
                                    continue
                                current = values.get(code)
                                if current is None:
                                    values[code] = v
                                elif isinstance(current, (int, float)) and isinstance(v, (int, float)):
                                    values[code] = current + v

                    derived_values = []
                    if options.use_preset:
                        for numerator, denominator, _label in DERIVED_SPECS:
                            derived_values.append(safe_ratio(values.get(numerator), values.get(denominator)))

                    geom = transform_geometry(merged_mesh_geometry(key, gassan), transformer)
                    attrs = [key, htk, row["HTKSAKI"], row["GASSAN"]]
                    attrs.extend(values[code] for code in value_codes)
                    attrs.extend(derived_values)
                    feat = QgsFeature(fields)
                    feat.setGeometry(geom)
                    feat.setAttributes(attrs)

                    if pref_writer is not None:
                        if not pref_writer.addFeature(feat, QgsFeatureSink.FastInsert):
                            raise RuntimeError(f"都道府県250m人口FGBへの書き込みに失敗: {key}")

                    muni = index.assign(key)
                    if muni is None:
                        unmatched_muni += 1
                    else:
                        if gassan:
                            component_codes = {muni.code}
                            for source_key in gassan:
                                source_muni = index.assign(source_key)
                                if source_muni:
                                    component_codes.add(source_muni.code)
                            if len(component_codes) > 1:
                                cross_muni += 1
                        muni_writer = writers.get(muni.code)
                        if muni_writer is not None:
                            if not muni_writer.addFeature(feat, QgsFeatureSink.FastInsert):
                                raise RuntimeError(
                                    f"自治体250m人口FGBへの書き込みに失敗: {muni.code} / {key}"
                                )
                    emitted += 1
            finally:
                # FlatGeobuf is finalized when the QgsVectorFileWriter object is destroyed.
                # Explicitly remove all local references before attempting to reopen files.
                try:
                    muni_writer = None
                except Exception:
                    pass
                if pref_writer is not None:
                    try:
                        pref_writer.flushBuffer()
                    except Exception:
                        pass
                    _pref_to_close = pref_writer
                    pref_writer = None
                    del _pref_to_close
                close_writers(writers)
                conn.close()

            self.log(
                f"人口メッシュ生成完了: {emitted:,}件 / 秘匿元除外 {skipped_suppressed:,}件"
            )
            if unmatched_muni:
                self.log(f"警告: 自治体に割り当てられなかったメッシュ {unmatched_muni:,}件")
            if cross_muni:
                self.log(
                    f"注意: 秘匿併合メッシュの構成要素が行政区域を跨ぐケース {cross_muni:,}件。"
                    "合算先KEY_CODEの中心点が属する自治体へ割り当てました。"
                )

        self.progress(93, "QGISへレイヤを追加しています")
        # Administrative layers: N03_007 ascending.
        for idx, code in enumerate(target_codes):
            muni = muni_by_code[code]
            add_layer_to_group(
                admin_paths[code], f"{muni.name}_行政区域_国土数値情報", "行政区域", idx,
                style_kind="admin",
            )

        # Prefecture layer at top, municipalities below in N03_007 order.
        add_layer_to_group(
            pref_pop, f"{options.pref_name}_250mメッシュ人口_2020国調", "250mメッシュ人口", 0,
            style_kind="population",
        )
        for idx, code in enumerate(target_codes, start=1):
            muni = muni_by_code[code]
            add_layer_to_group(
                muni_pop_paths[code], f"{muni.name}_250mメッシュ人口_2020国調",
                "250mメッシュ人口", idx, style_kind="population",
            )

        self.progress(100, "G-CHAMデータパックの作成が完了しました")
        return {
            "pref_population": pref_pop,
            "admin_paths": admin_paths,
            "population_paths": muni_pop_paths,
            "municipalities": [muni_by_code[c] for c in target_codes],
        }
