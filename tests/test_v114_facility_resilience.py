from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "gcham_datapack_builder" / "v114_facility_resilience.py"


class V114FacilityResilienceContracts(unittest.TestCase):
    def test_patch_is_applied_after_v113_workflow(self):
        source = (ROOT / "gcham_datapack_builder" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("apply_v114_facility_resilience", source)
        self.assertLess(source.index("apply_v113_unified_workflow()"), source.index("apply_v114_facility_resilience()"))

    def test_facility_layers_are_processed_independently(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("for spec in all_specs", source)
        self.assertIn("results.extend(partial)", source)
        self.assertIn("このレイヤをスキップして他の施設データを続行します", source)
        self.assertIn("except qgis_io.CancelledError", source)

    def test_lower_dimension_boundary_touch_is_skipped(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("_geometry_type(geom.wkbType()) != expected_geometry_type", source)
        self.assertIn("continue", source)
        self.assertIn("対象地物が0件でした", source)

    def test_population_group_is_normalized_after_incremental_build(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("def _normalize_population_group_order", source)
        self.assertIn('move_root_group_after("250mメッシュ人口", "災害")', source)
        self.assertIn('root.findGroup("背景地図")', source)
        self.assertIn("_patch_incremental_group_order", source)
        self.assertIn("_normalize_population_group_order()", source)

    def test_patch_parses(self):
        ast.parse(PATCH.read_text(encoding="utf-8"), filename=str(PATCH))


if __name__ == "__main__":
    unittest.main()
