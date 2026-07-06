import importlib.util
import hashlib
import pathlib
import unittest
from datetime import datetime


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "bluetti" / "hub_a1.py"
TEST_HUB_SERIAL = "TEST-HUB-A1-SERIAL"
TEST_APEX_SERIAL = "TEST-APEX-SERIAL1"


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

    def test_parse_hub_a1_serials_ignores_friendly_name_words(self):
        serials = self.hub_a1.parse_hub_a1_serials(
            f"Hub A1,HA1,A1,{TEST_HUB_SERIAL}"
        )

        self.assertEqual(serials, [TEST_HUB_SERIAL])

    def test_invalid_cached_hub_a1_product_detects_name_fragments(self):
        self.assertTrue(self.hub_a1.is_invalid_hub_a1_product({"model": "HA1", "sn": "Hub"}))
        self.assertTrue(self.hub_a1.is_invalid_hub_a1_product({"model": "HA1", "sn": "A1"}))
        self.assertFalse(self.hub_a1.is_invalid_hub_a1_product({"model": "HA1", "sn": TEST_HUB_SERIAL}))
        self.assertFalse(self.hub_a1.is_invalid_hub_a1_product({"model": "FP", "sn": "Hub"}))

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
        self.assertNotIn("HubA1BatterySoh", states_by_code)
        self.assertEqual(states_by_code["HubA1AcPowerOut"]["fnValue"], "2536")
        self.assertEqual(states_by_code["HubA1GridPowerIn"]["fnValue"], "2452")
        self.assertEqual(states_by_code["HubA1BatteryVoltage"]["sensorInfo"]["unit"], "V")
        self.assertNotIn("HubA1Pv1Power", states_by_code)
        self.assertNotIn("HubA1Pv2Voltage", states_by_code)
        self.assertEqual(states_by_code["HubA1AcSwitch"]["fnType"], "SENSOR")
        self.assertEqual(states_by_code["onLine"]["fnValue"], "1")

    def test_build_hub_a1_product_data_prefers_realtime_over_top_level_zero_placeholders(self):
        product = self.hub_a1.build_hub_a1_product_data(
            TEST_HUB_SERIAL,
            app_device={
                "sn": TEST_HUB_SERIAL,
                "name": "Garage Hub",
                "model": "HA1",
                "sessionState": "Online",
                "batSOC": "0",
                "powerAcOut": 0,
                "powerGridIn": 0,
                "powerPvIn": 0,
            },
            realtime={
                "batterySoc": "89",
                "powerLoadOut": "128",
                "powerGridIn": "12",
                "powerPvIn": "76",
            },
        )

        states_by_code = {state["fnCode"]: state for state in product["stateList"]}
        self.assertEqual(states_by_code["HubA1BatterySoc"]["fnValue"], "89")
        self.assertEqual(states_by_code["HubA1AcPowerOut"]["fnValue"], "128")
        self.assertEqual(states_by_code["HubA1GridPowerIn"]["fnValue"], "12")
        self.assertEqual(states_by_code["HubA1PvPowerIn"]["fnValue"], "76")

    def test_build_hub_a1_product_data_uses_direct_app_values_over_zero_optional_telemetry(self):
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
                "batterySoc": "0",
                "powerLoadOut": "0",
                "powerGridIn": "0",
                "powerPvIn": "0",
            },
            last_alive={
                "allFieldIsNull": True,
                "batterySoc": "0",
                "powerAcOut": "0",
                "powerGridIn": "0",
                "powerPvIn": "0",
            },
        )

        states_by_code = {state["fnCode"]: state for state in product["stateList"]}
        self.assertEqual(states_by_code["HubA1BatterySoc"]["fnValue"], "9")
        self.assertEqual(states_by_code["HubA1AcPowerOut"]["fnValue"], "2536")
        self.assertEqual(states_by_code["HubA1GridPowerIn"]["fnValue"], "2452")
        self.assertEqual(states_by_code["HubA1PvPowerIn"]["fnValue"], "0")

    def test_build_hub_a1_product_data_uses_last_alive_grid_alias(self):
        product = self.hub_a1.build_hub_a1_product_data(
            TEST_HUB_SERIAL,
            app_device={
                "sn": TEST_HUB_SERIAL,
                "name": "Garage Hub",
                "model": "HA1",
                "sessionState": "Online",
                "powerGridIn": "0",
            },
            realtime={"powerGridIn": "0"},
            last_alive={"powerFeedBack": "2452"},
        )

        states_by_code = {state["fnCode"]: state for state in product["stateList"]}
        self.assertEqual(states_by_code["HubA1GridPowerIn"]["fnValue"], "2452")

    def test_build_hub_a1_product_data_prefers_nonzero_last_alive_over_realtime_zero(self):
        product = self.hub_a1.build_hub_a1_product_data(
            TEST_HUB_SERIAL,
            app_device={"sn": TEST_HUB_SERIAL, "name": "Garage Hub", "model": "HA1"},
            realtime={
                "powerBatteryCharge": "0",
                "meterTotalEnergy": "0",
            },
            last_alive={
                "powerBatteryCharge": "42",
                "meterTotalEnergy": "13.7",
            },
        )

        states_by_code = {state["fnCode"]: state for state in product["stateList"]}
        self.assertEqual(states_by_code["HubA1BatteryChargePower"]["fnValue"], "42")
        self.assertNotIn("HubA1MeterTotalEnergy", states_by_code)

    def test_build_hub_a1_product_data_exposes_mirrored_pack_total_once_as_charge_energy(self):
        product = self.hub_a1.build_hub_a1_product_data(
            TEST_HUB_SERIAL,
            app_device={"sn": TEST_HUB_SERIAL, "name": "Garage Hub", "model": "HA1"},
            last_alive={
                "packTotalChgEnergy": "52975.0",
                "packTotalDsgEnergy": "52975.0",
            },
        )

        states_by_code = {state["fnCode"]: state for state in product["stateList"]}
        self.assertEqual(states_by_code["HubA1PackTotalChargeEnergy"]["fnValue"], "529.75")
        self.assertEqual(states_by_code["HubA1PackTotalChargeEnergy"]["fnName"], "Battery Total Charge Energy")
        self.assertEqual(states_by_code["HubA1PackTotalChargeEnergy"]["sensorInfo"]["unit"], "kWh")
        self.assertNotIn("HubA1PackTotalDischargeEnergy", states_by_code)

    def test_build_hub_a1_product_data_ignores_discharge_pack_total_even_when_divergent(self):
        product = self.hub_a1.build_hub_a1_product_data(
            TEST_HUB_SERIAL,
            app_device={"sn": TEST_HUB_SERIAL, "name": "Garage Hub", "model": "HA1"},
            last_alive={
                "packTotalChgEnergy": "52975.0",
                "packTotalDsgEnergy": "52970.0",
            },
        )

        states_by_code = {state["fnCode"]: state for state in product["stateList"]}
        self.assertEqual(states_by_code["HubA1PackTotalChargeEnergy"]["fnValue"], "529.75")
        self.assertNotIn("HubA1PackTotalDischargeEnergy", states_by_code)

    def test_build_hub_a1_product_data_keeps_detail_rows_with_nonzero_readings(self):
        product = self.hub_a1.build_hub_a1_product_data(
            TEST_HUB_SERIAL,
            app_device={"sn": TEST_HUB_SERIAL, "name": "Garage Hub", "model": "HA1"},
            pv_details=[
                {"portName": "PV1", "power": "0", "voltage": "0"},
                {"portName": "PV2", "power": "76", "voltage": "42"},
            ],
            load_details=[{"portName": "L1", "power": "128", "voltage": "120"}],
        )

        states_by_code = {state["fnCode"]: state for state in product["stateList"]}
        self.assertNotIn("HubA1Pv1Power", states_by_code)
        self.assertEqual(states_by_code["HubA1Pv2Power"]["fnValue"], "76")
        self.assertEqual(states_by_code["HubA1Pv2Voltage"]["fnValue"], "42")
        self.assertEqual(states_by_code["HubA1Load1Power"]["fnValue"], "128")

    def test_summarize_hub_a1_field_sources_reports_selected_aliases(self):
        summary = self.hub_a1.summarize_hub_a1_field_sources(
            app_device={"powerGridIn": "0"},
            realtime={"powerGridIn": "0"},
            last_alive={
                "powerFeedBack": "2452",
                "powerInvTotal": "-485",
                "packTotalChgEnergy": "55029.0",
                "packTotalDsgEnergy": "55029.0",
            },
        )

        self.assertIn("GridPowerIn=lastAlive.powerFeedBack:2452", summary)
        self.assertIn("InverterTotalPower=lastAlive.powerInvTotal:-485", summary)
        self.assertIn("BatterySoc=none", summary)
        self.assertIn("BatteryTotalChargeEnergy=lastAlive.packTotalChgEnergy:55029.0", summary)
        self.assertIn("PackTotalDischargeEnergy=ignored_displayed_as_charge:lastAlive.packTotalDsgEnergy:55029.0", summary)

    def test_build_app_device_state_overrides_prefers_last_alive_for_apex_zero_fields(self):
        states = self.hub_a1.build_app_device_state_overrides(
            {
                "model": "EL100V2",
                "sessionState": "Offline",
                "networkConnect": 1,
                "batSOC": "0",
                "powerAcOut": 0,
                "powerDcOut": 0,
                "powerGridIn": 0,
                "powerPvIn": 0,
                "lastAlive": {
                    "batterySoc": "89",
                    "powerAcOut": "128",
                    "powerDcOut": "0",
                    "powerGridIn": "0",
                    "powerPvIn": "76",
                    "chgFullTime": "5994",
                    "acSwitch": "1",
                    "dcSwitch": "0",
                },
            }
        )

        states_by_code = {state["fnCode"]: state for state in states}
        self.assertEqual(states_by_code["onLine"]["fnValue"], "1")
        self.assertEqual(states_by_code["SOC"]["fnValue"], "89")
        self.assertEqual(states_by_code["ACLoadAllTotalPower"]["fnValue"], "128")
        self.assertEqual(states_by_code["DCLoadAllTotalPower"]["fnValue"], "0")
        self.assertEqual(states_by_code["PVAllTotalPower"]["fnValue"], "76")
        self.assertEqual(states_by_code["ChgFullTime"]["fnValue"], "5994")
        self.assertEqual(states_by_code["SetCtrlAc"]["fnValue"], "1")
        self.assertEqual(states_by_code["SetCtrlDc"]["fnValue"], "0")

    def test_build_app_device_state_overrides_scales_pack_totals_as_centi_kwh(self):
        states = self.hub_a1.build_app_device_state_overrides(
            {
                "model": "FP",
                "sessionState": "Online",
                "lastAlive": {
                    "packTotalChgEnergy": "2344.0",
                    "packTotalDsgEnergy": "2230.0",
                },
            }
        )

        states_by_code = {state["fnCode"]: state for state in states}
        self.assertEqual(states_by_code["PackTotalChargeEnergy"]["fnValue"], "23.44")
        self.assertEqual(states_by_code["PackTotalChargeEnergy"]["sensorInfo"]["unit"], "kWh")
        self.assertEqual(states_by_code["PackTotalDischargeEnergy"]["fnValue"], "22.30")
        self.assertEqual(states_by_code["PackTotalDischargeEnergy"]["sensorInfo"]["unit"], "kWh")

    def test_select_preferred_app_device_payload_uses_home_last_alive_over_direct_zeros(self):
        direct = {
            "sn": TEST_APEX_SERIAL,
            "model": "EL100V2",
            "networkConnect": 1,
            "batSOC": "0",
            "powerAcOut": "0",
            "powerPvIn": "0",
        }
        home = {
            "sn": TEST_APEX_SERIAL,
            "model": "EL100V2",
            "networkConnect": 1,
            "batSOC": "0",
            "powerAcOut": "0",
            "powerPvIn": "0",
            "lastAlive": {
                "allFieldIsNull": False,
                "batterySoc": "89",
                "powerAcOut": "128",
                "powerPvIn": "76",
            },
        }

        selected = self.hub_a1.select_preferred_app_device_payload(
            TEST_APEX_SERIAL,
            direct,
            [home],
        )

        self.assertIs(selected, home)

    def test_select_preferred_app_device_payload_ignores_stale_home_last_alive(self):
        direct = {
            "sn": TEST_APEX_SERIAL,
            "model": "EL100V2",
            "networkConnect": 1,
            "batSOC": "0",
            "powerAcOut": "0",
            "powerPvIn": "0",
        }
        home = {
            "sn": TEST_APEX_SERIAL,
            "model": "EL100V2",
            "networkConnect": 1,
            "lastAlive": {
                "allFieldIsNull": False,
                "timestamp": "2026-07-04 13:00:00",
                "batterySoc": "89",
                "powerAcOut": "128",
                "powerPvIn": "76",
            },
        }

        selected = self.hub_a1.select_preferred_app_device_payload(
            TEST_APEX_SERIAL,
            direct,
            [home],
            now=datetime(2026, 7, 4, 14, 0, 0),
            max_age_seconds=900,
        )

        self.assertIs(selected, direct)

    def test_select_hub_a1_related_app_device_ignores_fresh_fp_without_verified_relation(self):
        fp = {
            "sn": "TEST-FP-SERIAL",
            "model": "FP",
            "lastAlive": {
                "timestamp": "2026-07-04 21:42:17",
                "batterySoc": "65",
                "powerAcOut": "66",
                "powerPvIn": "12",
            },
        }

        selected = self.hub_a1.select_hub_a1_related_app_device(
            [fp],
            now=datetime(2026, 7, 4, 21, 43, 0),
            max_age_seconds=900,
        )

        self.assertEqual(selected, {})

    def test_select_hub_a1_related_app_device_ignores_null_last_alive_payloads(self):
        selected = self.hub_a1.select_hub_a1_related_app_device(
            [
                {
                    "sn": TEST_APEX_SERIAL,
                    "model": "EL100V2",
                    "lastAlive": {
                        "allFieldIsNull": True,
                        "batterySoc": "0",
                        "powerAcOut": "0",
                        "powerPvIn": "0",
                    },
                }
            ]
        )

        self.assertEqual(selected, {})

    def test_select_hub_a1_related_app_device_ignores_stale_last_alive_payloads(self):
        selected = self.hub_a1.select_hub_a1_related_app_device(
            [
                {
                    "sn": TEST_APEX_SERIAL,
                    "model": "EL100V2",
                    "lastAlive": {
                        "allFieldIsNull": False,
                        "timestamp": "2026-07-04 13:00:00",
                        "batterySoc": "89",
                        "powerAcOut": "128",
                    },
                }
            ],
            now=datetime(2026, 7, 4, 14, 0, 0),
            max_age_seconds=900,
        )

        self.assertEqual(selected, {})

    def test_build_related_hub_a1_fallback_omits_apex_battery_fields(self):
        product = self.hub_a1.build_related_hub_a1_fallback_product_data(
            TEST_HUB_SERIAL,
            {
                "model": "EL100V2",
                "networkConnect": 1,
                "sessionState": "Online",
                "lastAlive": {
                    "batterySoc": "89",
                    "batterySoh": "100",
                    "batteryVoltage": "533",
                    "powerAcOut": "128",
                    "powerPvIn": "76",
                    "acSwitch": "1",
                },
            },
        )

        states_by_code = {state["fnCode"]: state for state in product["stateList"]}
        self.assertNotIn("HubA1BatterySoc", states_by_code)
        self.assertNotIn("HubA1BatterySoh", states_by_code)
        self.assertNotIn("HubA1BatteryVoltage", states_by_code)
        self.assertEqual(states_by_code["HubA1AcPowerOut"]["fnValue"], "128")
        self.assertEqual(states_by_code["HubA1PvPowerIn"]["fnValue"], "76")
        self.assertEqual(states_by_code["HubA1AcSwitch"]["fnValue"], "1")

    def test_build_related_hub_a1_fallback_omits_fp_battery_fields(self):
        product = self.hub_a1.build_related_hub_a1_fallback_product_data(
            TEST_HUB_SERIAL,
            {
                "model": "FP",
                "networkConnect": 1,
                "sessionState": "Online",
                "lastAlive": {
                    "timestamp": "2026-07-04 21:42:17",
                    "batterySoc": "44",
                    "batterySoh": "100",
                    "batteryVoltage": "533.0",
                    "powerAcOut": "69",
                    "powerPvIn": "0",
                    "acSwitch": "1",
                },
            },
        )

        states_by_code = {state["fnCode"]: state for state in product["stateList"]}
        self.assertNotIn("HubA1BatterySoc", states_by_code)
        self.assertNotIn("HubA1BatterySoh", states_by_code)
        self.assertNotIn("HubA1BatteryVoltage", states_by_code)
        self.assertEqual(states_by_code["HubA1AcPowerOut"]["fnValue"], "69")

    def test_build_app_device_state_overrides_returns_empty_without_app_payload(self):
        self.assertEqual(self.hub_a1.build_app_device_state_overrides({}), [])
        self.assertEqual(self.hub_a1.build_app_device_state_overrides(None), [])

    def test_apply_state_overrides_updates_cached_zero_product_before_entity_setup(self):
        product = {
            "sn": TEST_APEX_SERIAL,
            "model": "EL100V2",
            "name": "Apex",
            "online": "0",
            "stateList": [
                {
                    "fnCode": "SOC",
                    "fnName": "Battery Level",
                    "fnValue": "0",
                    "fnType": "SENSOR",
                    "sensorInfo": {"sensorType": "SensorDeviceClass.BATTERY", "unit": "%"},
                    "supportModeValues": [],
                },
                {
                    "fnCode": "ACLoadAllTotalPower",
                    "fnName": "Alternating Current Out Power",
                    "fnValue": "0",
                    "fnType": "SENSOR",
                    "sensorInfo": {"sensorType": "SensorDeviceClass.POWER", "unit": None},
                    "supportModeValues": [],
                },
                {
                    "fnCode": "SetCtrlWorkMode",
                    "fnName": "Working mode",
                    "fnValue": "workmode_3",
                    "fnType": "SELECT",
                    "sensorInfo": {},
                    "supportModeValues": [{"code": "workmode_3", "name": "Self-use"}],
                },
            ],
        }
        app_states = self.hub_a1.build_app_device_state_overrides(
            {
                "model": "EL100V2",
                "networkConnect": 1,
                "lastAlive": {
                    "batterySoc": "89",
                    "powerAcOut": "128",
                    "acSwitch": "1",
                },
            }
        )

        updated = self.hub_a1.apply_app_device_state_overrides(product, app_states)

        self.assertEqual(updated["online"], "1")
        states_by_code = {state["fnCode"]: state for state in updated["stateList"]}
        self.assertEqual(states_by_code["SOC"]["fnValue"], "89")
        self.assertEqual(states_by_code["SOC"]["sensorInfo"]["unit"], "%")
        self.assertEqual(states_by_code["ACLoadAllTotalPower"]["fnValue"], "128")
        self.assertEqual(states_by_code["SetCtrlWorkMode"]["supportModeValues"][0]["name"], "Self-use")
        self.assertEqual(states_by_code["SetCtrlAc"]["fnType"], "SWITCH")

    def test_summarize_state_values_omits_serials_and_counts_nonzero_values(self):
        summary = self.hub_a1.summarize_state_values(
            [
                {"fnCode": "SOC", "fnValue": "89"},
                {"fnCode": "ACLoadAllTotalPower", "fnValue": "128"},
                {"fnCode": "PVAllTotalPower", "fnValue": "0"},
                {"fnCode": TEST_HUB_SERIAL, "fnValue": TEST_APEX_SERIAL},
            ],
            limit=3,
        )

        self.assertIn("states=4", summary)
        self.assertIn("nonzero=3", summary)
        self.assertIn("zero=1", summary)
        self.assertIn("SOC=89", summary)
        self.assertIn("ACLoadAllTotalPower=128", summary)
        self.assertNotIn(TEST_HUB_SERIAL, summary)
        self.assertNotIn(TEST_APEX_SERIAL, summary)

    def test_has_meaningful_state_values_ignores_online_only(self):
        self.assertFalse(
            self.hub_a1.has_meaningful_state_values(
                [
                    {"fnCode": "onLine", "fnValue": "1"},
                    {"fnCode": "HubA1BatterySoc", "fnValue": "0"},
                    {"fnCode": "HubA1AcPowerOut", "fnValue": "0"},
                ]
            )
        )
        self.assertTrue(
            self.hub_a1.has_meaningful_state_values(
                [
                    {"fnCode": "onLine", "fnValue": "1"},
                    {"fnCode": "HubA1BatterySoc", "fnValue": "89"},
                ]
            )
        )

    def test_summarize_payload_values_counts_nested_values_and_redacts_identifiers(self):
        summary = self.hub_a1.summarize_payload_values(
            {
                "sn": TEST_HUB_SERIAL,
                "model": "HA1",
                "batSOC": "0",
                "powerAcOut": 2536,
                "powerGridIn": "2452",
                "powerPvIn": 0,
                "emptyField": "",
                "lastAlive": {
                    "batterySoc": "9",
                    "powerAcOut": "2536",
                    "serialEcho": TEST_APEX_SERIAL,
                },
            },
            limit=10,
        )

        self.assertIn("fields=", summary)
        self.assertIn("nonzero=", summary)
        self.assertIn("zero=2", summary)
        self.assertIn("empty=1", summary)
        self.assertIn("powerAcOut=2536", summary)
        self.assertIn("lastAlive.batterySoc=9", summary)
        self.assertNotIn("serialEcho", summary)
        self.assertNotIn(TEST_HUB_SERIAL, summary)
        self.assertNotIn(TEST_APEX_SERIAL, summary)

    def test_summarize_payload_values_handles_detail_rows_without_dumping_payloads(self):
        summary = self.hub_a1.summarize_payload_values(
            [
                {"portName": "PV1", "power": "0", "voltage": "0"},
                {"portName": "PV2", "power": "76", "voltage": "42.1"},
            ],
            limit=3,
        )

        self.assertIn("rows=2", summary)
        self.assertIn("fields=6", summary)
        self.assertIn("zero=2", summary)
        self.assertIn("PV2.power=76", summary)
        self.assertNotIn("raw", summary.lower())

    def test_summarize_serial_identity_hashes_without_exposing_value(self):
        summary = self.hub_a1.summarize_serial_identity(f" {TEST_HUB_SERIAL} ")
        digest = hashlib.sha256(TEST_HUB_SERIAL.encode("utf-8")).hexdigest()[:16]

        self.assertIn("len=18", summary)
        self.assertIn(f"sha256={digest}", summary)
        self.assertNotIn(TEST_HUB_SERIAL, summary)

    def test_summarize_app_home_device_serials_reports_redacted_target_match(self):
        summary = self.hub_a1.summarize_app_home_device_serials(
            TEST_HUB_SERIAL,
            [
                {"sn": TEST_APEX_SERIAL, "model": "FP"},
                {"sn": TEST_HUB_SERIAL, "model": "HA1"},
            ],
        )

        self.assertIn("home_devices=2", summary)
        self.assertIn("matches=1", summary)
        self.assertIn("HA1:len=18", summary)
        self.assertNotIn(TEST_HUB_SERIAL, summary)
        self.assertNotIn(TEST_APEX_SERIAL, summary)

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
        self.assertFalse(
            self.hub_a1.has_hub_a1_telemetry(
                realtime={},
                last_alive={},
                battery_details=[],
                pv_details=[{"power": "0", "voltage": "0"}],
                load_details=[],
                grid_details=[],
            )
        )
        self.assertTrue(
            self.hub_a1.has_hub_a1_telemetry(
                realtime={},
                last_alive={"acSwitch": "1"},
                battery_details=[],
                pv_details=[],
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
