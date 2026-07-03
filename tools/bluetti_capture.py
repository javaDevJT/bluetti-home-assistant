#!/usr/bin/env python3
"""Capture BLUETTI device payloads through a local OAuth browser flow."""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import secrets
import select
import socketserver
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SSO_BASE = "https://sso.bluettipower.com"
GATEWAY_BASE = "https://gw.bluettipower.com"
AUTHORIZE_PATH = "/oauth2/grant"
TOKEN_PATH = "/oauth2/token"
DEVICES_PATH = "/api/bluiotdata/ha/v1/devices"
DEVICE_STATES_PATH = "/api/bluiotdata/ha/v1/deviceStates"
KNOWN_READ_PROBE_PATHS = [
    "/api/blusmartprod/user/space/v1/getSpaceDeviceList",
    "/api/blusmartprod/device/group/v1/homeDevices",
    "/api/blusmartprod/device/group/v1/findDevicePage",
    "/api/blusmartprod/device/scene/v1/getAeccBindDeviceList",
]
KNOWN_SERIAL_READ_PROBE_TEMPLATES = [
    "/api/bluiotdata/aecc/v1/getDeviceRealTimeData?{param}={serial}",
    "/api/bluiotdata/aecc/v1/getDeviceBatteryDetailData?{param}={serial}",
    "/api/bluiotdata/aecc/v1/getDevicePvDetailData?{param}={serial}",
    "/api/bluiotdata/aecc/v1/getDeviceLoadDetailData?{param}={serial}",
    "/api/bluiotdata/aecc/v1/getDeviceGridDetailData?{param}={serial}",
    "/api/bluiotdata/realtime/v1/getDeviceLastAlive?{param}={serial}",
    "/api/blusmartprod/aecc/workMode/v1/getWorkMode?{param}={serial}",
    "/api/blusmartprod/aecc/advancedSetting/v1/getSettings?{param}={serial}",
    "/api/blusmartprod/aecc/command/v1/querySystemPowerData?{param}={serial}",
    "/api/blusmartprod/device/group/v1/findParallelDevice?{param}={serial}",
    "/api/blusmartprod/device/basic/v1/findDeviceByBluetooth?{param}={serial}",
    "/api/blusmartprod/device/basic/v1/deviceRemoteSearch?{param}={serial}",
]
KNOWN_SERIAL_PARAM_NAMES = ["sn", "deviceSn", "deviceSN", "deviceId"]
KNOWN_SERIAL_POST_PROBE_PATHS = [
    "/api/bluiotdata/aecc/v1/getDeviceRealTimeData",
    "/api/bluiotdata/aecc/v1/getDeviceBatteryDetailData",
    "/api/bluiotdata/aecc/v1/getDevicePvDetailData",
    "/api/bluiotdata/aecc/v1/getDeviceLoadDetailData",
    "/api/bluiotdata/aecc/v1/getDeviceGridDetailData",
    "/api/bluiotdata/realtime/v1/getDeviceLastAlive",
    "/api/blusmartprod/aecc/workMode/v1/getWorkMode",
    "/api/blusmartprod/aecc/advancedSetting/v1/getSettings",
    "/api/blusmartprod/aecc/command/v1/querySystemPowerData",
]
KNOWN_SERIAL_POST_PARAM_NAMES = ["deviceSn", "sn", "deviceSN", "deviceId"]

DEFAULT_CLIENT_ID = "HomeAssistant"
DEFAULT_CLIENT_SECRET = "SG9tZUFzc2lzdGFudA=="
DEFAULT_CALLBACK_HOST = "127.0.0.1"
DEFAULT_CALLBACK_PORT = 8765
DEFAULT_CALLBACK_PATH = "/callback"
DEFAULT_OAUTH_URL_FILE = "artifacts/bluetti-captures/oauth-url.txt"

SENSITIVE_KEYS = {
    "access_token",
    "authorization",
    "client_secret",
    "code",
    "cookie",
    "id_token",
    "password",
    "refresh_token",
    "set-cookie",
    "token",
}
SERIAL_KEYS = {
    "addressid",
    "boardsn",
    "bluetoothmac",
    "deviceid",
    "devicesn",
    "mac",
    "macaddress",
    "masterdevicesn",
    "messn",
    "rfidtid",
    "serial",
    "serialno",
    "serialnumber",
    "sn",
    "subsn",
    "userid",
}
DEVICE_NAME_KEYS = {"device_name", "devicename", "nickname", "productname"}


def stable_hash(value: Any) -> str:
    """Return a deterministic short hash for correlating redacted identifiers."""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def looks_like_serial_key(value: Any) -> bool:
    """Return true for object keys that look like device serial numbers."""
    if not isinstance(value, str):
        return False
    if value.startswith("sha256:"):
        return False
    if len(value) < 8 or len(value) > 64:
        return False
    has_digit = any(ch.isdigit() for ch in value)
    has_alpha = any(ch.isalpha() for ch in value)
    return has_digit and has_alpha and value.replace("-", "").replace("_", "").isalnum()


def redact_identifier_text(value: str) -> str:
    """Redact sensitive values embedded inside URL-like dict keys."""
    if "?" not in value:
        return value

    prefix = ""
    url_text = value
    if value.startswith(("GET ", "POST ")):
        prefix, url_text = value.split(" ", 1)
        prefix = f"{prefix} "

    parsed = urllib.parse.urlsplit(url_text)
    if not parsed.query:
        return value

    changed = False
    query_pairs: list[tuple[str, str]] = []
    for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        normalized = key.lower().replace("-", "_")
        if normalized in SENSITIVE_KEYS:
            query_pairs.append((key, "<redacted>"))
            changed = True
        elif normalized in SERIAL_KEYS:
            query_pairs.append((key, stable_hash(item)))
            changed = True
        else:
            query_pairs.append((key, item))

    if not changed:
        return value

    redacted_query = urllib.parse.urlencode(query_pairs)
    redacted_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, redacted_query, parsed.fragment)
    )
    return f"{prefix}{redacted_url}"


def redact_payload(value: Any, *, _inside_device: bool = False) -> Any:
    """Return a copy of a BLUETTI payload with secrets and device IDs redacted."""
    if isinstance(value, list):
        return [redact_payload(item, _inside_device=_inside_device) for item in value]

    if not isinstance(value, dict):
        return value

    lower_keys = {str(key).lower() for key in value}
    is_device = _inside_device or bool(lower_keys & SERIAL_KEYS)
    redacted: dict[str, Any] = {}

    for key, item in value.items():
        key_text = str(key)
        key_lower = key_text.lower()
        normalized = key_lower.replace("-", "_")
        output_key = stable_hash(key_text) if looks_like_serial_key(key_text) else redact_identifier_text(key_text)

        if normalized in SENSITIVE_KEYS or key_lower in SENSITIVE_KEYS:
            redacted[output_key] = "<redacted>"
        elif normalized in SERIAL_KEYS or key_lower in SERIAL_KEYS:
            redacted[output_key] = stable_hash(item)
        elif key_lower == "name" and is_device:
            redacted[output_key] = "<redacted-name>"
        elif normalized in DEVICE_NAME_KEYS:
            redacted[output_key] = "<redacted-name>"
        else:
            redacted[output_key] = redact_payload(item, _inside_device=is_device)

    return redacted


def value_shape(value: Any) -> str:
    """Describe a function value without exposing the value itself."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, str):
        if value == "":
            return "empty-string"
        try:
            float(value)
        except ValueError:
            return "string"
        return "numeric-string"
    return type(value).__name__


def _response_data(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, dict) and isinstance(response.get("data"), list):
        return response["data"]
    return []


def _first_state_record(state_response: Any, serial: str) -> dict[str, Any]:
    for record in _response_data(state_response):
        if isinstance(record, dict) and record.get("sn") == serial:
            return record
    data = _response_data(state_response)
    if data and isinstance(data[0], dict):
        return data[0]
    return {}


def _state_records(state_response: Any) -> list[dict[str, Any]]:
    return [record for record in _response_data(state_response) if isinstance(record, dict)]


def _summarize_device(
    serial: str,
    device: dict[str, Any],
    state_response: Any,
    *,
    in_devices_response: bool,
) -> dict[str, Any]:
    state_record = _first_state_record(state_response, serial)
    state_list = state_record.get("stateList") or device.get("stateList") or []
    functions = []

    for state in state_list:
        if not isinstance(state, dict):
            continue
        functions.append(
            {
                "fnCode": state.get("fnCode"),
                "fnName": state.get("fnName") or "",
                "fnType": state.get("fnType"),
                "value_shape": value_shape(state.get("fnValue")),
                "sensorInfo": state.get("sensorInfo") or {},
                "supportModeValues": state.get("supportModeValues") or [],
            }
        )

    state_msg_code = state_response.get("msgCode") if isinstance(state_response, dict) else None
    return {
        "serial_hash": stable_hash(serial),
        "source": "devices" if in_devices_response else "deviceStates",
        "in_devices_response": in_devices_response,
        "model": state_record.get("model") or device.get("model"),
        "online": state_record.get("online") or device.get("online"),
        "isBindByCurUser": state_record.get("isBindByCurUser") or device.get("isBindByCurUser"),
        "state_response_msgCode": state_msg_code,
        "state_count": len(functions),
        "function_types": _count_by_key(functions, "fnType"),
        "functions": functions,
    }


def summarize_capture(capture: dict[str, Any]) -> dict[str, Any]:
    """Extract device/function descriptors needed to implement support."""
    devices = _response_data(capture.get("devices"))
    states_by_serial = capture.get("device_states", {})
    summary_devices: list[dict[str, Any]] = []
    seen_serials: set[str] = set()

    for device in devices:
        if not isinstance(device, dict):
            continue

        serial = str(device.get("sn", ""))
        seen_serials.add(serial)
        summary_devices.append(_summarize_device(serial, device, states_by_serial.get(serial), in_devices_response=True))

    if isinstance(states_by_serial, dict):
        for serial, state_response in states_by_serial.items():
            serial = str(serial)
            if serial in seen_serials:
                continue
            records = _state_records(state_response)
            device = records[0] if records else {"sn": serial}
            summary_devices.append(_summarize_device(serial, device, state_response, in_devices_response=False))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "device_count": len(summary_devices),
        "devices": summary_devices,
    }


def _count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        label = str(item.get(key) or "unknown")
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Handle one local OAuth redirect without logging request details."""

    server: "OAuthCallbackServer"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        self.server.oauth_result = {
            "path": parsed.path,
            "code": params.get("code", [""])[0],
            "state": params.get("state", [""])[0],
            "error": params.get("error", [""])[0],
        }

        body = (
            "<html><body><h1>BLUETTI capture received</h1>"
            "<p>You can close this tab and return to the terminal.</p></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


class OAuthCallbackServer(http.server.HTTPServer):
    oauth_result: dict[str, str] | None = None

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{SSO_BASE}{AUTHORIZE_PATH}?{urllib.parse.urlencode(params)}"


def wait_for_oauth_code(
    host: str,
    port: int,
    path: str,
    client_id: str,
    timeout: int,
    open_browser: bool,
    oauth_url_file: Path | None = None,
) -> tuple[str, str]:
    redirect_uri = f"http://{host}:{port}{path}"
    state = secrets.token_urlsafe(24)
    authorize_url = build_authorize_url(client_id, redirect_uri, state)

    server = OAuthCallbackServer((host, port), OAuthCallbackHandler)

    if oauth_url_file is not None:
        oauth_url_file.parent.mkdir(parents=True, exist_ok=True)
        oauth_url_file.write_text(authorize_url + "\n", encoding="utf-8")

    print("Open this BLUETTI OAuth URL if your browser does not open automatically:", flush=True)
    print(authorize_url, flush=True)
    if open_browser:
        webbrowser.open(authorize_url)

    deadline = time.monotonic() + timeout
    try:
        while server.oauth_result is None and time.monotonic() < deadline:
            remaining = max(0.0, min(0.2, deadline - time.monotonic()))
            ready, _, _ = select.select([server.socket], [], [], remaining)
            if ready:
                server.handle_request()
    finally:
        server.server_close()

    if server.oauth_result is None:
        raise RuntimeError("Timed out waiting for BLUETTI OAuth callback")
    if not server.oauth_result:
        raise RuntimeError("OAuth callback did not return a result")
    if server.oauth_result.get("error"):
        raise RuntimeError(f"OAuth returned error: {server.oauth_result['error']}")
    if server.oauth_result.get("path") != path:
        raise RuntimeError("OAuth callback path did not match the expected path")
    if server.oauth_result.get("state") != state:
        raise RuntimeError("OAuth state mismatch")
    code = server.oauth_result.get("code")
    if not code:
        raise RuntimeError("OAuth callback did not include a code")
    return code, redirect_uri


def exchange_code_for_token(code: str, redirect_uri: str, client_id: str, client_secret: str) -> dict[str, Any]:
    form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{SSO_BASE}{TOKEN_PATH}",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return request_json(request)


def get_json(path: str, access_token: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    url = f"{GATEWAY_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Authorization": access_token})
    return request_json(request)


def post_json(path: str, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{GATEWAY_BASE}{path}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": access_token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return request_json(request)


def request_json(request: urllib.request.Request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        redacted = redact_payload({"status": exc.code, "body": body[:500]})
        raise RuntimeError(f"BLUETTI HTTP error: {json.dumps(redacted)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"BLUETTI request failed: {exc.reason}") from exc

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("BLUETTI response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("BLUETTI response JSON was not an object")
    return parsed


def capture_devices(
    access_token: str,
    extra_serials: list[str] | None = None,
    probe_get_paths: list[str] | None = None,
    probe_post_requests: list[tuple[str, dict[str, Any]]] | None = None,
    getter: Any = get_json,
    poster: Any = post_json,
) -> dict[str, Any]:
    devices = getter(DEVICES_PATH, access_token)
    device_states: dict[str, Any] = {}
    probes: dict[str, Any] = {}
    serials: list[str] = []

    for device in _response_data(devices):
        serial = device.get("sn") if isinstance(device, dict) else None
        if serial:
            serials.append(str(serial))

    for serial in extra_serials or []:
        serial = serial.strip()
        if serial and serial not in serials:
            serials.append(serial)

    for serial in serials:
        device_states[serial] = getter(DEVICE_STATES_PATH, access_token, {"sns": serial})

    for path in probe_get_paths or []:
        normalized_path = normalize_probe_path(path)
        try:
            probes[normalized_path] = getter(normalized_path, access_token)
        except Exception as exc:  # noqa: BLE001 - preserve exploratory probe failures in capture artifacts.
            probes[normalized_path] = {
                "ok": False,
                "error": str(exc),
            }

    for path, payload in probe_post_requests or []:
        normalized_path = normalize_probe_path(path)
        probe_key = format_probe_request_key("POST", normalized_path, payload)
        try:
            probes[probe_key] = {
                "method": "POST",
                "path": normalized_path,
                "request": {"json": payload},
                "response": poster(normalized_path, access_token, payload),
            }
        except Exception as exc:  # noqa: BLE001 - preserve exploratory probe failures in capture artifacts.
            probes[probe_key] = {
                "ok": False,
                "method": "POST",
                "path": normalized_path,
                "request": {"json": payload},
                "error": str(exc),
            }

    return {"devices": devices, "device_states": device_states, "probes": probes}


def format_probe_request_key(method: str, path: str, payload: dict[str, Any] | None = None) -> str:
    if not payload:
        return f"{method.upper()} {path}"

    parts = []
    for key, value in sorted(payload.items()):
        normalized = str(key).lower().replace("-", "_")
        if normalized in SENSITIVE_KEYS:
            display_value = "<redacted>"
        elif normalized in SERIAL_KEYS:
            display_value = stable_hash(value)
        elif isinstance(value, str | int | float | bool) or value is None:
            display_value = str(value)
        else:
            display_value = value_shape(value)
        parts.append(f"{key}={display_value}")
    return f"{method.upper()} {path} {'&'.join(parts)}"


def normalize_probe_path(path: str) -> str:
    path = path.strip()
    if not path:
        raise ValueError("Probe path cannot be empty")
    if path.startswith("https://gw.bluettipower.com"):
        parsed = urllib.parse.urlparse(path)
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
    if not path.startswith("/"):
        path = f"/{path}"
    if not path.startswith("/api/"):
        raise ValueError("Probe path must be a BLUETTI /api/ path")
    return path


def write_capture(capture: dict[str, Any], output_root: Path, include_raw_private: bool) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / timestamp
    output_dir.mkdir(parents=True, exist_ok=False)

    summary = summarize_capture(capture)
    redacted = redact_payload(capture)
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "redacted.json", redacted)
    if include_raw_private:
        _write_json(output_dir / "raw.private.json", capture)
    return output_dir


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture BLUETTI OAuth device payloads locally.")
    parser.add_argument("--output-dir", default="artifacts/bluetti-captures")
    parser.add_argument("--callback-host", default=DEFAULT_CALLBACK_HOST)
    parser.add_argument("--callback-port", type=int, default=DEFAULT_CALLBACK_PORT)
    parser.add_argument("--callback-path", default=DEFAULT_CALLBACK_PATH)
    parser.add_argument("--oauth-url-file", default=DEFAULT_OAUTH_URL_FILE)
    parser.add_argument("--client-id", default=os.environ.get("BLUETTI_CLIENT_ID", DEFAULT_CLIENT_ID))
    parser.add_argument("--client-secret", default=os.environ.get("BLUETTI_CLIENT_SECRET", DEFAULT_CLIENT_SECRET))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--extra-sn",
        action="append",
        default=[],
        help="Also query deviceStates for this serial even if /devices omits it. Repeatable.",
    )
    parser.add_argument(
        "--extra-sn-file",
        help="File containing additional serial numbers to query, one per line.",
    )
    parser.add_argument(
        "--probe-get",
        action="append",
        default=[],
        help="Also capture a raw read-only GET response from this BLUETTI /api/ path. Repeatable.",
    )
    parser.add_argument(
        "--probe-post-json",
        action="append",
        default=[],
        help=(
            "Also capture a raw read-only POST JSON response from this BLUETTI /api/ path, "
            "formatted as /api/path={\"deviceSn\":\"...\"}. Repeatable."
        ),
    )
    parser.add_argument(
        "--probe-known-read",
        action="store_true",
        help="Capture known read-only BLUETTI app/device endpoints that may list devices omitted by the HA endpoint.",
    )
    parser.add_argument("--no-browser", action="store_true", help="Print the OAuth URL without opening a browser.")
    parser.add_argument(
        "--raw-private",
        action="store_true",
        help="Also write raw.private.json. This file may contain serial numbers and device names.",
    )
    return parser.parse_args(argv)


def load_extra_serials(args: argparse.Namespace) -> list[str]:
    serials = list(args.extra_sn or [])
    if args.extra_sn_file:
        path = Path(args.extra_sn_file)
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                serials.append(value)
    return serials


def load_probe_paths(args: argparse.Namespace) -> list[str]:
    paths = list(args.probe_get or [])
    if args.probe_known_read:
        paths.extend(KNOWN_READ_PROBE_PATHS)
        for serial in load_extra_serials(args):
            encoded_serial = urllib.parse.quote(serial, safe="")
            for template in KNOWN_SERIAL_READ_PROBE_TEMPLATES:
                for param in KNOWN_SERIAL_PARAM_NAMES:
                    paths.append(template.format(param=param, serial=encoded_serial))

    normalized: list[str] = []
    for path in paths:
        probe_path = normalize_probe_path(path)
        if probe_path not in normalized:
            normalized.append(probe_path)
    return normalized


def load_probe_post_requests(args: argparse.Namespace) -> list[tuple[str, dict[str, Any]]]:
    requests: list[tuple[str, dict[str, Any]]] = []

    for value in args.probe_post_json or []:
        requests.append(parse_probe_post_json(value))

    if args.probe_known_read:
        for serial in load_extra_serials(args):
            for path in KNOWN_SERIAL_POST_PROBE_PATHS:
                for param in KNOWN_SERIAL_POST_PARAM_NAMES:
                    requests.append((path, {param: serial}))

    normalized: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for path, payload in requests:
        normalized_path = normalize_probe_path(path)
        key = json.dumps([normalized_path, payload], sort_keys=True)
        if key not in seen:
            seen.add(key)
            normalized.append((normalized_path, payload))
    return normalized


def parse_probe_post_json(value: str) -> tuple[str, dict[str, Any]]:
    if "=" not in value:
        raise ValueError("--probe-post-json must be formatted as /api/path={...}")
    path, payload_text = value.split("=", 1)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ValueError("--probe-post-json payload must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("--probe-post-json payload must be a JSON object")
    return normalize_probe_path(path), payload


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    code, redirect_uri = wait_for_oauth_code(
        args.callback_host,
        args.callback_port,
        args.callback_path,
        args.client_id,
        args.timeout,
        not args.no_browser,
        Path(args.oauth_url_file) if args.oauth_url_file else None,
    )
    token = exchange_code_for_token(code, redirect_uri, args.client_id, args.client_secret)
    access_token = token.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Token response did not include access_token")

    capture = capture_devices(
        access_token,
        load_extra_serials(args),
        load_probe_paths(args),
        load_probe_post_requests(args),
    )
    output_dir = write_capture(capture, Path(args.output_dir), args.raw_private)
    summary = summarize_capture(capture)
    print(f"Capture written to: {output_dir}")
    print(f"Devices captured: {summary['device_count']}")
    print("Share summary.json and redacted.json for implementation work.")
    if args.raw_private:
        print("raw.private.json was written by explicit request; do not share it publicly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
