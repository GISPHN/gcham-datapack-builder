from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "gcham_datapack_builder" / "v114_population_group_position.py"
PROCESSOR = ROOT / "gcham_datapack_builder" / "processor.py"


class V114PopulationGroupPositionContracts(unittest.TestCase):
    def test_population_processing_is_not_reimplemented(self):
        source = PATCH.read_text(encoding="utf-8")
        for forbidden in (
            "BuildOptions",
            "STAT_TABLES",
            "iter_estat_rows",
            "create_fgb_writer",
            "merged_mesh_geometry",
            "safe_ratio",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("QgsProject.instance()", source)

    def test_existing_project_population_layers_are_reused(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("project.mapLayers().values()", source)
        self.assertIn("census2020_", source)
        self.assertIn("_pop250m.fgb", source)
        self.assertIn("group.addLayer(layer)", source)
        self.assertNotIn("QgsVectorLayer(", source)
        self.assertNotIn("removeMapLayer", source)

    def test_requested_group_position_is_disaster_then_population_then_background(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn('root.findGroup("災害")', source)
        self.assertIn('root.findGroup("背景地図")', source)
        self.assertIn("root.insertGroup", source)

    def test_empty_tree_group_can_self_repair(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("Self-repair", source)
        self.assertIn("expected_ids.issubset(existing_ids)", source)

    def test_patch_runs_after_v113_and_facility_patch(self):
        source = (ROOT / "gcham_datapack_builder" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("apply_v114_population_group_position", source)
        self.assertLess(
            source.index("apply_v114_facility_resilience()"),
            source.index("apply_v114_population_group_position()"),
        )

    def test_established_processor_population_path_remains_present(self):
        source = PROCESSOR.read_text(encoding="utf-8")
        self.assertIn('add_layer_to_group(\n            pref_pop', source)
        self.assertIn('"250mメッシュ人口", 0', source)
        self.assertIn("muni_pop_paths[code]", source)
        self.assertIn('"250mメッシュ人口", idx', source)

    def test_patch_parses(self):
        ast.parse(PATCH.read_text(encoding="utf-8"), filename=str(PATCH))


if __name__ == "__main__":
    unittest.main()
