from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "gcham_datapack_builder"
WORKFLOW = PLUGIN / "v113_unified_workflow.py"


def _function_source(function_name: str) -> str:
    source = WORKFLOW.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(WORKFLOW))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            segment = ast.get_source_segment(source, node)
            if segment:
                return segment
    raise AssertionError(f"missing function: {function_name}")


class UnifiedWorkflowContractsTest(unittest.TestCase):
    def test_population_is_a_peer_dataset(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('POPULATION_KEY = "population_census"', source)
        self.assertIn('QTreeWidgetItem(["人口データ"])', source)
        self.assertIn("250mメッシュ人口（2020年国勢調査）", source)

    def test_datapack_selects_everything_except_roads(self):
        source = _function_source("_select_datapack")
        self.assertIn('set(v113_layer_selection.ALL_LAYER_KEYS) - {"road_n13"}', source)
        self.assertIn("_set_tree_selection", source)

    def test_specific_data_button_clears_all_checks(self):
        source = _function_source("_select_specific")
        self.assertIn("_set_tree_selection(dialog, set())", source)

    def test_user_no_longer_operates_layer_only_mode(self):
        source = _function_source("_build_ui")
        self.assertIn("self.layer_only_check.setVisible(False)", source)
        run_source = _function_source("_run_build")
        self.assertIn("self.layer_only_check.setChecked(not population_selected)", run_source)

    def test_population_controls_are_inside_unified_panel(self):
        source = _function_source("_build_ui")
        self.assertIn('self.extra_button.setText("人口項目を選択...")', source)
        self.assertIn("data_layout.insertLayout", source)
        self.assertIn("old_population_group.setVisible(False)", source)

    def test_selected_municipality_full_pack_scopes_supplementals(self):
        run_source = _function_source("_run_build")
        self.assertIn("_run_population_and_scoped_supplementals", run_source)
        scoped = _function_source("_run_population_and_scoped_supplementals")
        self.assertIn("all_municipalities=False", scoped)
        self.assertIn("selected_municipality_codes=set(self._selected_muni_codes)", scoped)
        self.assertIn("v113_layer_selection._build_supplemental_only", scoped)

    def test_no_dataset_selected_is_rejected_before_output(self):
        source = _function_source("_run_build")
        warning_pos = source.index("QMessageBox.warning")
        output_pos = source.find("_ensure_output_dir")
        self.assertTrue(output_pos == -1 or warning_pos < output_pos)


if __name__ == "__main__":
    unittest.main()
