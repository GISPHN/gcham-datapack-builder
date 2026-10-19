"""Exercise the QGIS-free release logic and inspect the installed entry points."""
from __future__ import annotations

import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

PLUGIN = Path(__file__).resolve().parents[1] / "gcham_datapack_builder"


def load_functions(name, *function_names, namespace=None):
    source = PLUGIN.joinpath(name).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=name)
    selected = [node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in function_names]
    if len(selected) != len(function_names):
        raise AssertionError("release function missing")
    module = ast.Module(body=selected, type_ignores=[])
    scope = {} if namespace is None else namespace
    exec(compile(module, name, "exec"), scope)
    return scope


class V115ReleaseTests(unittest.TestCase):
    def test_road_candidate_uses_class_and_toll_not_construction_status(self):
        scope = load_functions("v114_n13_catalogue.py", "_code", "_walk_cycle_candidate",
                               namespace={"_ALLOWED_CLASSES": {1, 2, 3, 5}})
        candidate = scope["_walk_cycle_candidate"]
        for road_class in (1, 2, 3, 5):
            self.assertTrue(candidate({"N13_003": str(road_class), "N13_007": "1"}))
        for road_class, toll in ((4, 1), (1, 2), (None, 1)):
            self.assertFalse(candidate({"N13_003": road_class, "N13_007": toll}))

    def test_catalogue_parsing_rejects_missing_or_incomplete_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder = SimpleNamespace(cache=Path(tmp))
            def download(url, path, log=None):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(" ".join(f"N13-24_{code:04d}_SHP.zip"
                                         for code in range(3820, 3840)), encoding="utf-8")
            scope = load_functions(
                "v114_n13_catalogue.py", "_published_n13_meshes",
                namespace={"qgis_io": SimpleNamespace(download_file=download),
                           "OFFICIAL_N13_PAGE": "https://example.org/catalogue",
                           "N13_ARCHIVE_PATTERN": __import__("re").compile(
                               r"N13-24_([0-9]{4})_SHP\.zip", __import__("re").I)})
            self.assertEqual(len(scope["_published_n13_meshes"](builder)), 20)
            scope["qgis_io"].download_file = lambda url, path, log=None: path.write_text(
                "N13-24_3820_SHP.zip", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                scope["_published_n13_meshes"](builder)

    def test_entry_points_include_all_three_new_modules(self):
        entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
        for name in ("combined_admin", "n13_catalogue", "gsi_csv_recovery"):
            self.assertIn(f"apply_v114_{name}()", entry)


if __name__ == "__main__":
    unittest.main()
