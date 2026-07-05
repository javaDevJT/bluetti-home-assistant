import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class HacsMetadataTests(unittest.TestCase):
    def test_hacs_and_manifest_metadata_are_release_ready(self):
        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        manifest = json.loads(
            (ROOT / "custom_components" / "bluetti" / "manifest.json").read_text(encoding="utf-8")
        )

        self.assertEqual(hacs["name"], "BLUETTI Apex and Hub A1")
        self.assertEqual(manifest["version"], "1.1.13")
        self.assertEqual(manifest["codeowners"], ["@javaDevJT"])
        self.assertEqual(
            manifest["documentation"],
            "https://github.com/javaDevJT/bluetti-home-assistant",
        )
        self.assertEqual(
            manifest["issue_tracker"],
            "https://github.com/javaDevJT/bluetti-home-assistant/issues",
        )


if __name__ == "__main__":
    unittest.main()
