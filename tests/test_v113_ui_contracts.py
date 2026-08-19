from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "gcham_datapack_builder"


def _function_sources(path: Path, function_name: str) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    matches = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            segment = ast.get_source_segment(source, node)
            if segment:
                matches.append(segment)
    return matches


class V113UIContractsTest(unittest.TestCase):
    def test_selection_buttons_do_not_request_output_folder(self):
        path = PLUGIN / "v113_preflight_ui.py"
        for name in ("_choose_municipalities", "_choose_additional_data"):
            functions = _function_sources(path, name)
            self.assertTrue(functions, f"missing {name}")
            for source in functions:
                self.assertNotIn("_ensure_output_dir", source)
                self.assertIn("_standard_cache_location", source)

    def test_create_action_still_requests_output_folder(self):
        path = PLUGIN / "v113_layer_selection.py"
        functions = _function_sources(path, "_run_build")
        self.assertTrue(functions)
        self.assertTrue(any("_ensure_output_dir" in source for source in functions))

    def test_layer_only_run_restores_controls_after_completion(self):
        path = PLUGIN / "v113_layer_selection.py"
        functions = _function_sources(path, "_run_build")
        self.assertTrue(functions)
        self.assertTrue(any("self._set_running(False)" in source for source in functions))

    def test_municipality_scope_preserves_dialog_selection(self):
        path = PLUGIN / "v113_municipality_scope.py"
        functions = _function_sources(path, "_run_build")
        self.assertTrue(functions)
        for source in functions:
            self.assertNotIn("self._selected_muni_codes.clear", source)
            self.assertNotIn("self.output_edit.clear", source)

    def test_municipality_outputs_use_municipality_code(self):
        source = (PLUGIN / "v113_municipality_scope.py").read_text(encoding="utf-8")
        self.assertIn("_municipality_result_path", source)
        self.assertIn("municipality.code", source)
        self.assertIn("municipality.name", source)

    def test_internal_result_is_never_renamed(self):
        source = (PLUGIN / "v113_safety.py").read_text(encoding="utf-8")
        self.assertIn("result.group == v113_layer_selection._INTERNAL_GROUP", source)
        self.assertIn("return result", source)


if __name__ == "__main__":
    unittest.main()
