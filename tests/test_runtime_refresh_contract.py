import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RuntimeRefreshContractTests(unittest.TestCase):
    def test_integration_registers_periodic_device_refresh(self):
        init_source = (ROOT / "custom_components" / "bluetti" / "__init__.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("async_track_time_interval", init_source)
        self.assertIn("timedelta(seconds=60)", init_source)
        self.assertIn("refresh_unsub", init_source)
        self.assertIn("await device.async_update()", init_source)
        self.assertIn("BLUETTI periodic runtime state summary", init_source)

    def test_unload_cancels_periodic_device_refresh(self):
        init_source = (ROOT / "custom_components" / "bluetti" / "__init__.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('data.get("refresh_unsub")', init_source)
        self.assertIn("refresh_unsub()", init_source)


if __name__ == "__main__":
    unittest.main()
