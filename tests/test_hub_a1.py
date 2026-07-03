import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "bluetti" / "hub_a1.py"
TEST_HUB_SERIAL = "TEST-HUB-A1-SERIAL"
TEST_APEX_SERIAL = "TEST-APEX-SERIAL"


def load_module():
    spec = importlib.util.spec_from_file_location("hub_a1", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("hub_a1 module is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HubA1Tests(unittest.TestCase):
    def setUp(self):
        self.hub_a1 = load_module()

    def test_parse_hub_a1_serials_splits_commas_lines_and_deduplicates(self):
        serials = self.hub_a1.parse_hub_a1_serials(
            f" {TEST_HUB_SERIAL}, {TEST_APEX_SERIAL}\n{TEST_HUB_SERIAL}  "
        )

        self.assertEqual(serials, [TEST_HUB_SERIAL, TEST_APEX_SERIAL])

    def test_build_hub_a1_product_data_uses_app_identity_and_telemetry(self):
        product = self.hub_a1.build_hub_a1_product_data(
            TEST_HUB_SERIAL,
            app_device={
                "sn": TEST_HUB_SERIAL,
                "name": "Garage Hub",
                "model": "HA1",
                "sessionState": "Online",
                "batSOC": "9",
                "powerAcOut": 2536,
                "powerGridIn": 2452,
                "powerPvIn": 0,
                "powerDcOut": 0,
            },
            realtime={
                "batterySoc": "9",
                "powerBatteryCharge": "0",
                "powerGridIn": "2452",
                "powerLoadOut": "2536",
                "powerPvIn": "0",
                "meterTotalEnergy": "12.3",
            },
            last_alive={
                "batterySoh": "12",
                "batteryVoltage": "515.6",
                "acSwitch": "1",
                "dcSwitch": "0",
                "gridSwitch": "0",
                "dcTotalEnergy": "4.5",
            },
            pv_details=[
                {"portName": "PV1", "power": "0", "voltage": "0"},
                {"portName": "PV2", "power": "0", "voltage": "0"},
            ],
        )

        self.assertEqual(product["sn"], TEST_HUB_SERIAL)
        self.assertEqual(product["name"], "Garage Hub")
        self.assertEqual(product["model"], "HA1")
        self.assertEqual(product["online"], "1")
        states_by_code = {state["fnCode"]: state for state in product["stateList"]}
        self.assertEqual(states_by_code["HubA1BatterySoc"]["fnValue"], "9")
        self.assertEqual(states_by_code["HubA1BatterySoc"]["sensorInfo"]["unit"], "%")
        self.assertEqual(states_by_code["HubA1AcPowerOut"]["fnValue"], "2536")
        self.assertEqual(states_by_code["HubA1GridPowerIn"]["fnValue"], "2452")
        self.assertEqual(states_by_code["HubA1BatteryVoltage"]["sensorInfo"]["unit"], "V")
        self.assertEqual(states_by_code["HubA1Pv1Power"]["fnName"], "PV1 Power")
        self.assertEqual(states_by_code["HubA1Pv2Voltage"]["fnName"], "PV2 Voltage")
        self.assertEqual(states_by_code["HubA1AcSwitch"]["fnType"], "SENSOR")
        self.assertEqual(states_by_code["onLine"]["fnValue"], "1")

    def test_build_hub_a1_product_data_falls_back_to_serial_name(self):
        product = self.hub_a1.build_hub_a1_product_data(
            TEST_HUB_SERIAL,
            app_device={"model": "HA1"},
            realtime={},
            last_alive={},
        )

        self.assertEqual(product["name"], TEST_HUB_SERIAL)
        self.assertEqual(product["online"], "0")
        self.assertEqual(product["stateList"][0]["fnCode"], "onLine")

    def test_has_hub_a1_telemetry_detects_fallback_payloads(self):
        self.assertFalse(
            self.hub_a1.has_hub_a1_telemetry(
                realtime={},
                last_alive={},
                battery_details=[],
                pv_details=[],
                load_details=[],
                grid_details=[],
            )
        )
        self.assertTrue(
            self.hub_a1.has_hub_a1_telemetry(
                realtime={"batterySoc": "9"},
                last_alive={},
                battery_details=[],
                pv_details=[],
                load_details=[],
                grid_details=[],
            )
        )
        self.assertTrue(
            self.hub_a1.has_hub_a1_telemetry(
                realtime={},
                last_alive={},
                battery_details=[],
                pv_details=[{"power": "0", "voltage": "0"}],
                load_details=[],
                grid_details=[],
            )
        )

    def test_describe_hub_a1_lookup_response_avoids_identifiers(self):
        class Response:
            msgCode = -2
            code = -2
            message = "Invalid serial TEST-HUB-A1-SERIAL"
            data = None

        description = self.hub_a1.describe_hub_a1_lookup_response(Response())

        self.assertIn("msgCode=-2", description)
        self.assertIn("code=-2", description)
        self.assertIn("message=Invalid serial <redacted>", description)
        self.assertNotIn(TEST_HUB_SERIAL, description)


if __name__ == "__main__":
    unittest.main()
