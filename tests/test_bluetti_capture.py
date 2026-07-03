import importlib.util
import multiprocessing
import pathlib
import tempfile
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "tools" / "bluetti_capture.py"
TEST_HUB_SERIAL = "TEST-HUB-A1-SERIAL"


def load_module():
    spec = importlib.util.spec_from_file_location("bluetti_capture", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("bluetti_capture module is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_wait_for_oauth_code(module_path, url_file, queue):
    spec = importlib.util.spec_from_file_location("bluetti_capture_child", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.wait_for_oauth_code(
            "127.0.0.1",
            8991,
            "/callback",
            module.DEFAULT_CLIENT_ID,
            1,
            False,
            pathlib.Path(url_file),
        )
    except Exception as exc:
        queue.put((type(exc).__name__, str(exc)))
    else:
        queue.put(("ok", ""))


class BluettiCaptureTests(unittest.TestCase):
    def setUp(self):
        self.capture = load_module()

    def test_redacts_sensitive_tokens_and_device_identifiers(self):
        payload = {
            "access_token": "access-token-value",
            "refresh_token": "refresh-token-value",
            "authorization": "secret-header",
            "data": [
                {
                    "sn": "AP300SERIAL123",
                    "name": "Garage Apex",
                    "model": "AP300",
                    "stateList": [
                        {
                            "fnCode": "SOC",
                            "fnName": "Battery SOC",
                            "fnType": "SENSOR",
                            "fnValue": "87",
                            "sensorInfo": {"unit": "%"},
                        }
                    ],
                }
            ],
        }

        redacted = self.capture.redact_payload(payload)

        self.assertEqual(redacted["access_token"], "<redacted>")
        self.assertEqual(redacted["refresh_token"], "<redacted>")
        self.assertEqual(redacted["authorization"], "<redacted>")
        device = redacted["data"][0]
        self.assertNotEqual(device["sn"], "AP300SERIAL123")
        self.assertTrue(device["sn"].startswith("sha256:"))
        self.assertEqual(device["name"], "<redacted-name>")
        self.assertEqual(device["model"], "AP300")
        self.assertEqual(device["stateList"][0]["fnName"], "Battery SOC")

    def test_redacts_serials_used_as_device_state_keys(self):
        payload = {
            "device_states": {
                "AP300SERIAL123": {
                    "msgCode": 0,
                    "data": [{"sn": "AP300SERIAL123", "stateList": []}],
                }
            }
        }

        redacted = self.capture.redact_payload(payload)

        keys = list(redacted["device_states"].keys())
        self.assertEqual(len(keys), 1)
        self.assertNotEqual(keys[0], "AP300SERIAL123")
        self.assertTrue(keys[0].startswith("sha256:"))
        record = redacted["device_states"][keys[0]]["data"][0]
        self.assertEqual(record["sn"], keys[0])

    def test_redacts_serials_embedded_in_probe_query_keys(self):
        payload = {
            "probes": {
                "/api/blusmartprod/device/basic/v1/deviceRemoteSearch?deviceSn=AP300SERIAL123": {
                    "msgCode": 0,
                    "data": {"sn": "AP300SERIAL123"},
                }
            }
        }

        redacted = self.capture.redact_payload(payload)

        keys = list(redacted["probes"].keys())
        self.assertEqual(len(keys), 1)
        self.assertIn("deviceSn=sha256%3A", keys[0])
        self.assertNotIn("AP300SERIAL123", keys[0])

    def test_redacts_extended_app_device_identifier_fields(self):
        payload = {
            "boardSn": "BOARD123456",
            "subSn": "SUB123456",
            "mac": "AA:BB:CC:DD:EE:FF",
            "addressId": "address-identifier",
            "deviceId": "device-identifier",
            "mesSn": "MES1234567890",
            "userId": "user-identifier",
        }

        redacted = self.capture.redact_payload(payload)

        for key in payload:
            self.assertNotEqual(redacted[key], payload[key])
            self.assertTrue(redacted[key].startswith("sha256:"))

    def test_summarizes_state_descriptors_by_device(self):
        capture = {
            "devices": {
                "data": [
                    {"sn": "AP300SERIAL123", "name": "Garage Apex", "model": "AP300"}
                ]
            },
            "device_states": {
                "AP300SERIAL123": {
                    "data": [
                        {
                            "sn": "AP300SERIAL123",
                            "model": "AP300",
                            "stateList": [
                                {
                                    "fnCode": "SOC",
                                    "fnName": "Battery SOC",
                                    "fnType": "SENSOR",
                                    "fnValue": "87",
                                    "sensorInfo": {"unit": "%"},
                                },
                                {
                                    "fnCode": "SetCtrlWorkMode",
                                    "fnName": "Work Mode",
                                    "fnType": "MODE",
                                    "fnValue": "1",
                                    "supportModeValues": [
                                        {"code": "1", "name": "Backup"},
                                        {"code": "2", "name": "Self Consumption"},
                                    ],
                                },
                            ],
                        }
                    ]
                }
            },
        }

        summary = self.capture.summarize_capture(capture)

        self.assertEqual(summary["device_count"], 1)
        device = summary["devices"][0]
        self.assertEqual(device["model"], "AP300")
        self.assertTrue(device["serial_hash"].startswith("sha256:"))
        self.assertEqual(device["state_count"], 2)
        self.assertEqual(
            device["functions"][0],
            {
                "fnCode": "SOC",
                "fnName": "Battery SOC",
                "fnType": "SENSOR",
                "value_shape": "numeric-string",
                "sensorInfo": {"unit": "%"},
                "supportModeValues": [],
            },
        )
        self.assertEqual(device["functions"][1]["supportModeValues"][0]["name"], "Backup")

    def test_summarizes_state_only_extra_serials_missing_from_devices(self):
        capture = {
            "devices": {"msgCode": 0, "data": []},
            "device_states": {
                TEST_HUB_SERIAL: {
                    "msgCode": 0,
                    "message": "OK",
                    "data": [
                        {
                            "sn": TEST_HUB_SERIAL,
                            "online": "0",
                            "isBindByCurUser": "0",
                            "stateList": [],
                        }
                    ],
                }
            },
        }

        summary = self.capture.summarize_capture(capture)

        self.assertEqual(summary["device_count"], 1)
        device = summary["devices"][0]
        self.assertFalse(device["in_devices_response"])
        self.assertEqual(device["source"], "deviceStates")
        self.assertEqual(device["isBindByCurUser"], "0")
        self.assertEqual(device["state_response_msgCode"], 0)
        self.assertEqual(device["state_count"], 0)

    def test_oauth_wait_writes_url_file_and_times_out_promptly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            url_file = pathlib.Path(tmpdir) / "oauth-url.txt"
            ctx = multiprocessing.get_context("fork")
            queue = ctx.Queue()
            process = ctx.Process(
                target=run_wait_for_oauth_code,
                args=(str(MODULE_PATH), str(url_file), queue),
            )

            process.start()
            process.join(3)
            if process.is_alive():
                process.terminate()
                process.join(1)
                self.fail("OAuth wait did not time out promptly")

            self.assertTrue(url_file.exists())
            self.assertIn("/oauth2/grant?", url_file.read_text(encoding="utf-8"))
            status, message = queue.get_nowait()
            self.assertEqual(status, "RuntimeError")
            self.assertIn("Timed out waiting", message)

    def test_capture_devices_queries_extra_serials_missing_from_devices_response(self):
        calls = []

        def fake_get_json(path, access_token, params=None):
            calls.append((path, params))
            if path == self.capture.DEVICES_PATH:
                return {
                    "msgCode": 0,
                    "data": [
                        {"sn": "RETURNED123", "model": "FP", "stateList": []}
                    ],
                }
            return {
                "msgCode": 0,
                "data": [
                    {
                        "sn": params["sns"],
                        "model": "AP300",
                        "stateList": [
                            {"fnCode": "SOC", "fnType": "SENSOR", "fnValue": "88"}
                        ],
                    }
                ],
            }

        capture = self.capture.capture_devices(
            "token-value",
            extra_serials=["MISSING456", "RETURNED123"],
            getter=fake_get_json,
        )

        self.assertEqual(
            calls,
            [
                (self.capture.DEVICES_PATH, None),
                (self.capture.DEVICE_STATES_PATH, {"sns": "RETURNED123"}),
                (self.capture.DEVICE_STATES_PATH, {"sns": "MISSING456"}),
            ],
        )
        self.assertIn("MISSING456", capture["device_states"])

    def test_capture_devices_can_probe_read_only_app_endpoints(self):
        calls = []

        def fake_get_json(path, access_token, params=None):
            calls.append((path, params))
            if path == self.capture.DEVICES_PATH:
                return {"msgCode": 0, "data": []}
            return {"msgCode": 0, "data": [{"deviceType": "HubA1"}]}

        capture = self.capture.capture_devices(
            "token-value",
            probe_get_paths=["/api/blusmartprod/user/space/v1/getSpaceDeviceList"],
            getter=fake_get_json,
        )

        self.assertEqual(
            calls,
            [
                (self.capture.DEVICES_PATH, None),
                ("/api/blusmartprod/user/space/v1/getSpaceDeviceList", None),
            ],
        )
        self.assertEqual(
            capture["probes"]["/api/blusmartprod/user/space/v1/getSpaceDeviceList"]["data"][0]["deviceType"],
            "HubA1",
        )

    def test_known_read_probe_paths_include_serialized_aecc_variants(self):
        args = self.capture.parse_args(
            [
                "--probe-known-read",
                "--extra-sn",
                TEST_HUB_SERIAL,
            ]
        )

        paths = self.capture.load_probe_paths(args)

        self.assertIn("/api/blusmartprod/device/group/v1/homeDevices", paths)
        self.assertIn(
            f"/api/bluiotdata/aecc/v1/getDeviceRealTimeData?sn={TEST_HUB_SERIAL}",
            paths,
        )
        self.assertIn(
            f"/api/bluiotdata/aecc/v1/getDeviceRealTimeData?deviceSn={TEST_HUB_SERIAL}",
            paths,
        )

    def test_probe_errors_are_recorded_without_aborting_capture(self):
        calls = []

        def fake_get_json(path, access_token, params=None):
            calls.append((path, params))
            if path == self.capture.DEVICES_PATH:
                return {"msgCode": 0, "data": []}
            if path == "/api/blusmartprod/device/group/v1/findDevicePage":
                raise RuntimeError("BLUETTI HTTP error: 500")
            return {"msgCode": 0, "data": [{"deviceType": "HubA1"}]}

        capture = self.capture.capture_devices(
            "token-value",
            probe_get_paths=[
                "/api/blusmartprod/device/group/v1/findDevicePage",
                "/api/blusmartprod/user/space/v1/getSpaceDeviceList",
            ],
            getter=fake_get_json,
        )

        self.assertEqual(
            calls,
            [
                (self.capture.DEVICES_PATH, None),
                ("/api/blusmartprod/device/group/v1/findDevicePage", None),
                ("/api/blusmartprod/user/space/v1/getSpaceDeviceList", None),
            ],
        )
        failed_probe = capture["probes"]["/api/blusmartprod/device/group/v1/findDevicePage"]
        self.assertFalse(failed_probe["ok"])
        self.assertIn("500", failed_probe["error"])
        successful_probe = capture["probes"]["/api/blusmartprod/user/space/v1/getSpaceDeviceList"]
        self.assertEqual(successful_probe["data"][0]["deviceType"], "HubA1")

    def test_capture_devices_can_probe_read_only_post_endpoints(self):
        calls = []

        def fake_get_json(path, access_token, params=None):
            calls.append(("GET", path, params))
            if path == self.capture.DEVICES_PATH:
                return {"msgCode": 0, "data": []}
            return {"msgCode": 0, "data": []}

        def fake_post_json(path, access_token, payload):
            calls.append(("POST", path, payload))
            return {"msgCode": 0, "data": [{"model": "HA1"}]}

        capture = self.capture.capture_devices(
            "token-value",
            probe_post_requests=[
                (
                    "/api/bluiotdata/aecc/v1/getDeviceRealTimeData",
                    {"deviceSn": TEST_HUB_SERIAL},
                )
            ],
            getter=fake_get_json,
            poster=fake_post_json,
        )

        self.assertEqual(
            calls,
            [
                ("GET", self.capture.DEVICES_PATH, None),
                (
                    "POST",
                    "/api/bluiotdata/aecc/v1/getDeviceRealTimeData",
                    {"deviceSn": TEST_HUB_SERIAL},
                ),
            ],
        )
        probe_key = (
            "POST /api/bluiotdata/aecc/v1/getDeviceRealTimeData "
            f"deviceSn={self.capture.stable_hash(TEST_HUB_SERIAL)}"
        )
        self.assertEqual(capture["probes"][probe_key]["response"]["data"][0]["model"], "HA1")

    def test_known_read_probe_requests_include_serial_post_variants(self):
        args = self.capture.parse_args(
            [
                "--probe-known-read",
                "--extra-sn",
                TEST_HUB_SERIAL,
            ]
        )

        requests = self.capture.load_probe_post_requests(args)

        self.assertIn(
            (
                "/api/bluiotdata/aecc/v1/getDeviceRealTimeData",
                {"deviceSn": TEST_HUB_SERIAL},
            ),
            requests,
        )
        self.assertIn(
            (
                "/api/blusmartprod/aecc/command/v1/querySystemPowerData",
                {"deviceSn": TEST_HUB_SERIAL},
            ),
            requests,
        )

    def test_loads_explicit_post_json_probe_requests(self):
        args = self.capture.parse_args(
            [
                "--probe-post-json",
                f'/api/bluiotdata/aecc/v1/getDeviceRealTimeData={{"deviceSn":"{TEST_HUB_SERIAL}"}}',
            ]
        )

        requests = self.capture.load_probe_post_requests(args)

        self.assertEqual(
            requests,
            [
                (
                    "/api/bluiotdata/aecc/v1/getDeviceRealTimeData",
                    {"deviceSn": TEST_HUB_SERIAL},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
