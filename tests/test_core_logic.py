import unittest
from pathlib import Path

from gcham_datapack_builder.core_logic import (
    ascii_admin_filename,
    ascii_population_filename,
    ascii_pref_population_filename,
    load_preset_config,
    mesh250_bbox,
    mesh250_center,
    safe_ratio,
)


class CoreLogicTests(unittest.TestCase):
    def test_ascii_filenames(self):
        self.assertEqual(ascii_admin_filename("29201"), "n03_29201_admin.fgb")
        self.assertEqual(ascii_population_filename("29201"), "census2020_29201_pop250m.fgb")
        self.assertEqual(ascii_pref_population_filename("29"), "census2020_29_pop250m.fgb")

    def test_safe_ratio_half_up_one_decimal(self):
        self.assertEqual(safe_ratio(1235, 10000), 12.4)
        self.assertEqual(safe_ratio(1234, 10000), 12.3)
        self.assertIsNone(safe_ratio(1, 0))
        self.assertIsNone(safe_ratio(None, 100))

    def test_mesh_center_is_inside_bbox(self):
        west, south, east, north = mesh250_bbox("5235061234")
        lon, lat = mesh250_center("5235061234")
        self.assertGreater(lon, west)
        self.assertLess(lon, east)
        self.assertGreater(lat, south)
        self.assertLess(lat, north)

    def test_preset_has_128_source_fields_and_3_derived_fields(self):
        plugin_dir = Path(__file__).resolve().parents[1] / "gcham_datapack_builder"
        config = load_preset_config(plugin_dir)
        self.assertEqual(len(config["fields"]), 128)
        self.assertEqual(len(config["derived_fields"]), 3)


if __name__ == "__main__":
    unittest.main()
