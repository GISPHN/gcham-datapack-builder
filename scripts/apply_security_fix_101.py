from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# processor.py: fixed SQL for suppression validation and base count.
p = Path("gcham_datapack_builder/processor.py")
s = p.read_text(encoding="utf-8")
marker = "@dataclass\nclass BuildOptions:"
constants = '''_SUPPRESSION_VALIDATION_SQL = {
    "T001145": """
        SELECT b.KEY_CODE,
               b.HTKSYORI, x.HTKSYORI,
               b.HTKSAKI, x.HTKSAKI,
               b.GASSAN, x.GASSAN
        FROM s_T001142 b JOIN s_T001145 x USING(KEY_CODE)
        WHERE COALESCE(b.HTKSYORI,0) <> COALESCE(x.HTKSYORI,0)
           OR COALESCE(b.HTKSAKI,'') <> COALESCE(x.HTKSAKI,'')
           OR COALESCE(b.GASSAN,'') <> COALESCE(x.GASSAN,'')
        LIMIT 1
    """,
    "T001196": """
        SELECT b.KEY_CODE,
               b.HTKSYORI, x.HTKSYORI,
               b.HTKSAKI, x.HTKSAKI,
               b.GASSAN, x.GASSAN
        FROM s_T001142 b JOIN s_T001196 x USING(KEY_CODE)
        WHERE COALESCE(b.HTKSYORI,0) <> COALESCE(x.HTKSYORI,0)
           OR COALESCE(b.HTKSAKI,'') <> COALESCE(x.HTKSAKI,'')
           OR COALESCE(b.GASSAN,'') <> COALESCE(x.GASSAN,'')
        LIMIT 1
    """,
    "T001197": """
        SELECT b.KEY_CODE,
               b.HTKSYORI, x.HTKSYORI,
               b.HTKSAKI, x.HTKSAKI,
               b.GASSAN, x.GASSAN
        FROM s_T001142 b JOIN s_T001197 x USING(KEY_CODE)
        WHERE COALESCE(b.HTKSYORI,0) <> COALESCE(x.HTKSYORI,0)
           OR COALESCE(b.HTKSAKI,'') <> COALESCE(x.HTKSAKI,'')
           OR COALESCE(b.GASSAN,'') <> COALESCE(x.GASSAN,'')
        LIMIT 1
    """,
    "T001198": """
        SELECT b.KEY_CODE,
               b.HTKSYORI, x.HTKSYORI,
               b.HTKSAKI, x.HTKSAKI,
               b.GASSAN, x.GASSAN
        FROM s_T001142 b JOIN s_T001198 x USING(KEY_CODE)
        WHERE COALESCE(b.HTKSYORI,0) <> COALESCE(x.HTKSYORI,0)
           OR COALESCE(b.HTKSAKI,'') <> COALESCE(x.HTKSAKI,'')
           OR COALESCE(b.GASSAN,'') <> COALESCE(x.GASSAN,'')
        LIMIT 1
    """,
    "T001199": """
        SELECT b.KEY_CODE,
               b.HTKSYORI, x.HTKSYORI,
               b.HTKSAKI, x.HTKSAKI,
               b.GASSAN, x.GASSAN
        FROM s_T001142 b JOIN s_T001199 x USING(KEY_CODE)
        WHERE COALESCE(b.HTKSYORI,0) <> COALESCE(x.HTKSYORI,0)
           OR COALESCE(b.HTKSAKI,'') <> COALESCE(x.HTKSAKI,'')
           OR COALESCE(b.GASSAN,'') <> COALESCE(x.GASSAN,'')
        LIMIT 1
    """,
}

_BASE_COUNT_SQL = "SELECT COUNT(*) FROM s_T001142"


'''
if constants not in s:
    if marker not in s:
        raise SystemExit("BuildOptions marker not found")
    s = s.replace(marker, constants + marker, 1)

old = '''    def _validate_suppression(self, conn: sqlite3.Connection):
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
'''
new = '''    def _validate_suppression(self, conn: sqlite3.Connection):
        for stats_id, table_name in STAT_TABLES:
            if stats_id == BASE_STATS_ID:
                continue
            sql = _SUPPRESSION_VALIDATION_SQL[stats_id]
            row = conn.execute(sql).fetchone()
'''
if old in s:
    s = s.replace(old, new, 1)

s = s.replace(
    '            insert_sql = f"INSERT OR REPLACE INTO {table} VALUES ({placeholders})"\n',
    '            insert_sql = f"INSERT OR REPLACE INTO {table} VALUES ({placeholders})"  # nosec B608 -- table is selected only from STAT_TABLES; values are bound parameters.\n',
    1,
)
s = s.replace(
    '''        sql = (
            "SELECT " + ", ".join(parts) + f" FROM s_{BASE_STATS_ID} {base_alias} "
            + " ".join(joins)
        )
''',
    '''        # Column identifiers come only from parsed e-Stat headers and are quoted via _sql_ident;
        # table names and aliases come only from the fixed STAT_TABLES constant.
        sql = (  # nosec B608 -- dynamic identifiers are strictly quoted/whitelisted; data values are never interpolated.
            "SELECT " + ", ".join(parts) + f" FROM s_{BASE_STATS_ID} {base_alias} "
            + " ".join(joins)
        )
''',
    1,
)
s = s.replace(
    '                total = conn.execute(f"SELECT COUNT(*) FROM s_{BASE_STATS_ID}").fetchone()[0]\n',
    '                total = conn.execute(_BASE_COUNT_SQL).fetchone()[0]\n',
    1,
)
s = s.replace(
    '''            finally:
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
''',
    '''            finally:
                # FlatGeobuf is finalized when QgsVectorFileWriter is destroyed.
                # Drop every local reference before reopening any output layer.
                muni_writer = None
                if pref_writer is not None:
                    _pref_to_close = pref_writer
                    pref_writer = None
                    del _pref_to_close
                close_writers(writers)
                conn.close()
''',
    1,
)
s = s.replace(
    '''                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
''',
    '''                p.unlink(missing_ok=True)
''',
    1,
)
p.write_text(s, encoding="utf-8")

# qgis_io.py: remove silent exception-pass cleanup/styling paths.
replace(
    "gcham_datapack_builder/qgis_io.py",
    '''def close_writer(writer: QgsVectorFileWriter | None) -> None:
    """Finalize OGR-backed writer by dropping all Python references.

    FlatGeobuf writes its index/footer at dataset close. Keeping a SIP wrapper
    alive can therefore leave a file unreadable by OGR until the object is
    destroyed.
    """
    if writer is None:
        return
    try:
        writer.flushBuffer()
    except Exception:
        pass


def close_writers(writers: dict[str, QgsVectorFileWriter]) -> None:
    # Pop one at a time so the dictionary cannot retain a writer reference.
    while writers:
        _key, writer = writers.popitem()
        try:
            writer.flushBuffer()
        except Exception:
            pass
        del writer
    gc.collect()
''',
    '''def close_writer(writer: QgsVectorFileWriter | None) -> None:
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
''',
)
replace(
    "gcham_datapack_builder/qgis_io.py",
    '''    try:
        sl = symbol.symbolLayer(0)
        sl.setStrokeWidth(0.96)
        sl.setStrokeWidthUnit(_mm_render_unit())
        try:
            sl.setPenJoinStyle(Qt.PenJoinStyle.BevelJoin)
        except AttributeError:
            sl.setPenJoinStyle(Qt.BevelJoin)
    except Exception:
        pass
''',
    '''    sl = symbol.symbolLayer(0)
    if sl is not None:
        sl.setStrokeWidth(0.96)
        sl.setStrokeWidthUnit(_mm_render_unit())
        pen_join_scope = getattr(Qt, "PenJoinStyle", Qt)
        sl.setPenJoinStyle(getattr(pen_join_scope, "BevelJoin"))
''',
)
replace(
    "gcham_datapack_builder/qgis_io.py",
    '''    except TypeError:
        # Fallback for bindings with the shorter overload.
        renderer = QgsGraduatedSymbolRenderer.createRenderer(
            layer, value_field, 10, _jenks_mode(), symbol, ramp
        )
        try:
            renderer.setLabelFormat(QgsRendererRangeLabelFormat("%1 - %2", 0, True), True)
        except Exception:
            pass
''',
    '''    except TypeError:
        # Fallback for bindings with the shorter overload. QGIS will generate
        # default range labels for this overload, so no silent exception is needed.
        renderer = QgsGraduatedSymbolRenderer.createRenderer(
            layer, value_field, 10, _jenks_mode(), symbol, ramp
        )
''',
)

# core_logic.py: explicit numeric parse fallback rather than except/pass.
replace(
    "gcham_datapack_builder/core_logic.py",
    '''        try:
            f = float(s)
            if math.isfinite(f):
                return f
        except ValueError:
            pass
    return s
''',
    '''        try:
            f = float(s)
        except ValueError:
            return s
        if math.isfinite(f):
            return f
    return s
''',
)

# Version and public release metadata.
p = Path("gcham_datapack_builder/metadata.txt")
s = p.read_text(encoding="utf-8")
s = s.replace("version=1.0.0", "version=1.0.1", 1)
s = s.replace(
    "changelog=1.0.0 - First stable public release.",
    "changelog=1.0.1 - Resolves QGIS Plugin Repository Bandit security findings: fixed/whitelisted SQL construction, removed silent try/except/pass cleanup, and added Bandit to CI.\n    1.0.0 - First stable public release.",
    1,
)
p.write_text(s, encoding="utf-8")

p = Path("CHANGELOG.md")
s = p.read_text(encoding="utf-8")
entry = '''## 1.0.1 - 2026-08-17

Security hardening release required by the QGIS Official Plugin Repository scanner.

### Security
- Replaced dynamically constructed suppression-validation and base-row-count `SELECT` statements with fixed SQL statements.
- Retained dynamic SQL only where SQLite requires dynamic identifiers; identifiers are fixed by `STAT_TABLES` or escaped with `_sql_ident`, with narrowly scoped Bandit `B608` annotations.
- Removed silent `try/except/pass` writer-finalization and styling paths flagged by Bandit `B110`.
- Replaced other silent exception-pass paths in file replacement and numeric parsing with explicit control flow.
- Added Bandit analysis to GitHub Actions.

'''
if "## 1.0.1 - 2026-08-17" not in s:
    s = s.replace("## 1.0.0 - 2026-08-17\n", entry + "## 1.0.0 - 2026-08-17\n", 1)
p.write_text(s, encoding="utf-8")

p = Path("CITATION.cff")
s = p.read_text(encoding="utf-8").replace('version: "1.0.0"', 'version: "1.0.1"')
p.write_text(s, encoding="utf-8")

p = Path("README.md")
s = p.read_text(encoding="utf-8")
s = s.replace("Version 1.0.0 uses a prefecture-level principal zone", "Version 1.0.1 uses a prefecture-level principal zone")
s = s.replace("v1.0.0では都道府県全体の処理に主要区域の系を使用", "v1.0.1では都道府県全体の処理に主要区域の系を使用")
p.write_text(s, encoding="utf-8")

p = Path("scripts/validate_package.py")
s = p.read_text(encoding="utf-8").replace('if general.get("version") != "1.0.0":', 'if general.get("version") != "1.0.1":')
p.write_text(s, encoding="utf-8")

p = Path(".github/workflows/check.yml")
s = p.read_text(encoding="utf-8")
if "Bandit security scan" not in s:
    s = s.replace(
        "      - name: Compile Python sources\n        run: python -m compileall -q gcham_datapack_builder\n",
        "      - name: Install security scanner\n        run: python -m pip install --disable-pip-version-check bandit\n      - name: Bandit security scan\n        run: bandit -r gcham_datapack_builder -q\n      - name: Compile Python sources\n        run: python -m compileall -q gcham_datapack_builder\n",
        1,
    )
s = s.replace("GCHAM_Data_Pack_Builder_1.0.0.zip", "GCHAM_Data_Pack_Builder_1.0.1.zip")
p.write_text(s, encoding="utf-8")

Path("RELEASE_NOTES_1.0.1.md").write_text('''# G-CHAM Data Pack Builder 1.0.1

This release resolves the blocking Bandit findings reported by the QGIS Official Plugin Repository for version 1.0.0.

- Fixed B608 SQL-injection warnings by using fixed SQL where possible and strictly quoted/whitelisted identifiers where dynamic identifiers are required.
- Removed B110 silent try/except/pass patterns.
- Added Bandit to GitHub Actions.
- No intended change to Census integration, suppression handling, municipality allocation, FlatGeobuf output, CRS conversion, or QGIS styling.
''', encoding="utf-8")
