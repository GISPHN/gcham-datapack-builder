from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "gcham_datapack_builder" / "v114_population_order_fix.py"


class V114PopulationOrderFixContracts(unittest.TestCase):
    def test_only_group_position_is_changed(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn('root.findGroup("250mメッシュ人口")', source)
        self.assertIn("root.takeChild(population)", source)
        self.assertIn("root.insertChildNode", source)
        self.assertNotIn("population.clone()", source)
        self.assertNotIn("removeMapLayer", source)

    def test_existing_population_processing_is_not_reimplemented(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertNotIn("BuildOptions", source)
        self.assertNotIn("pref_population", source)
        self.assertNotIn("population_paths", source)
        self.assertIn("_normalize_population_group_order", source)

    def test_patch_runs_after_facility_resilience(self):
        source = (ROOT / "gcham_datapack_builder" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("apply_v114_population_order_fix", source)
        self.assertLess(
            source.index("apply_v114_facility_resilience()"),
            source.index("apply_v114_population_order_fix()"),
        )

    def test_patch_parses(self):
        ast.parse(PATCH.read_text(encoding="utf-8"), filename=str(PATCH))


if __name__ == "__main__":
    unittest.main()
