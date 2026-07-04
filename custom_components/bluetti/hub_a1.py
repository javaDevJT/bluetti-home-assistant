"""Hub A1 helpers for BLUETTI app API payloads."""

from __future__ import annotations

import re
from typing import Any


HUB_A1_MODEL = "HA1"

SENSOR_TYPE_BATTERY = "SensorDeviceClass.BATTERY"
SENSOR_TYPE_ENERGY = "SensorDeviceClass.ENERGY"
SENSOR_TYPE_POWER = "SensorDeviceClass.POWER"
SENSOR_TYPE_VOLTAGE = "SensorDeviceClass.VOLTAGE"


class HubA1LookupError(RuntimeError):
    """Raised when a Hub A1 cannot be resolved from app or telemetry APIs."""


def parse_hub_a1_serials(value: Any) -> list[str]:
    """Parse a comma/whitespace separated Hub A1 serial field."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value]
    else:
        parts = [part.strip() for part in re.split(r"[\s,;]+", str(value))]

    serials: list[str] = []
    for part in parts:
        if part and part not in serials:
            serials.append(part)
    return serials


def build_hub_a1_product_data(
    serial: str,
    *,
    app_device: dict[str, Any] | None = None,
    realtime: dict[str, Any] | None = None,
    last_alive: dict[str, Any] | None = None,
    battery_details: list[dict[str, Any]] | None = None,
    pv_details: list[dict[str, Any]] | None = None,
    load_details: list[dict[str, Any]] | None = None,
    grid_details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a synthetic UserProduct-shaped dict from Hub A1 app telemetry."""
    app_device = app_device or {}
    realtime = realtime or {}
    last_alive = last_alive or {}

    return {
        "sn": serial,
        "stateList": build_hub_a1_state_list(
            app_device=app_device,
            realtime=realtime,
            last_alive=last_alive,
            battery_details=battery_details,
            pv_details=pv_details,
            load_details=load_details,
            grid_details=grid_details,
        ),
        "online": _online_value(app_device, last_alive),
        "model": app_device.get("model") or HUB_A1_MODEL,
        "name": app_device.get("name") or serial,
        "isBindByCurUser": "1",
    }


def has_hub_a1_telemetry(
    *,
    realtime: dict[str, Any] | None,
    last_alive: dict[str, Any] | None,
    battery_details: list[dict[str, Any]] | None,
    pv_details: list[dict[str, Any]] | None,
    load_details: list[dict[str, Any]] | None,
    grid_details: list[dict[str, Any]] | None,
) -> bool:
    """Return true when any Hub A1 telemetry endpoint returned usable data."""
    return any(
        bool(value)
        for value in (
            realtime,
            last_alive,
            battery_details,
            pv_details,
            load_details,
            grid_details,
        )
    )


def describe_hub_a1_lookup_response(response: Any) -> str:
    """Return a safe, identifier-redacted description of a BLUETTI response."""
    parts = []
    for key in ("msgCode", "code", "message"):
        if hasattr(response, key):
            value = _redact_identifier_text(str(getattr(response, key)))
            parts.append(f"{key}={value}")
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        parts.append(f"data_keys={len(data)}")
    elif isinstance(data, list):
        parts.append(f"data_len={len(data)}")
    elif data is None:
        parts.append("data=None")
    else:
        parts.append(f"data_type={type(data).__name__}")
    return ", ".join(parts) if parts else type(response).__name__


def summarize_state_values(states: list[Any], *, limit: int = 6) -> str:
    """Return a serial-safe summary of state values for diagnostics."""
    total = 0
    zero = 0
    nonzero = 0
    empty = 0
    samples: list[str] = []

    for state in states:
        if isinstance(state, dict):
            fn_code = state.get("fnCode")
            value = state.get("fnValue")
        else:
            fn_code = getattr(state, "fn_code", None)
            value = getattr(state, "fn_value", None)

        if not fn_code:
            continue

        total += 1
        value_text = "" if value is None else str(value)
        if value_text == "":
            empty += 1
            continue
        if _is_zero_value(value_text):
            zero += 1
            continue

        nonzero += 1
        if len(samples) < limit:
            safe_code = _redact_identifier_text(str(fn_code))
            safe_value = _redact_identifier_text(value_text)
            samples.append(f"{safe_code}={safe_value}")

    sample_text = ",".join(samples) if samples else "none"
    return f"states={total} nonzero={nonzero} zero={zero} empty={empty} samples={sample_text}"


def build_hub_a1_state_list(
    *,
    app_device: dict[str, Any] | None = None,
    realtime: dict[str, Any] | None = None,
    last_alive: dict[str, Any] | None = None,
    battery_details: list[dict[str, Any]] | None = None,
    pv_details: list[dict[str, Any]] | None = None,
    load_details: list[dict[str, Any]] | None = None,
    grid_details: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return state descriptors consumable by the existing BLUETTI entities."""
    app_device = app_device or {}
    realtime = realtime or {}
    last_alive = last_alive or {}
    battery_details = battery_details or []
    pv_details = pv_details or []
    load_details = load_details or []
    grid_details = grid_details or []

    states = [
        _binary_sensor("onLine", "Online", _online_value(app_device, last_alive)),
        _battery_sensor("HubA1BatterySoc", "Battery SOC", _first(last_alive.get("batterySoc"), realtime.get("batterySoc"), app_device.get("batSOC"))),
        _battery_sensor("HubA1BatterySoh", "Battery SOH", last_alive.get("batterySoh")),
        _voltage_sensor(
            "HubA1BatteryVoltage",
            "Battery Voltage",
            _first(last_alive.get("batteryVoltage"), _first_detail_value(battery_details, "voltage")),
        ),
        _power_sensor("HubA1AcPowerOut", "AC Output Power", _first(realtime.get("powerLoadOut"), last_alive.get("powerAcOut"), app_device.get("powerAcOut"))),
        _power_sensor("HubA1DcPowerOut", "DC Output Power", _first(last_alive.get("powerDcOut"), app_device.get("powerDcOut"))),
        _power_sensor("HubA1GridPowerIn", "Grid Input Power", _first(realtime.get("powerGridIn"), last_alive.get("powerGridIn"), app_device.get("powerGridIn"))),
        _power_sensor("HubA1PvPowerIn", "PV Input Power", _first(realtime.get("powerPvIn"), last_alive.get("powerPvIn"), app_device.get("powerPvIn"))),
        _power_sensor("HubA1BatteryChargePower", "Battery Charge Power", realtime.get("powerBatteryCharge")),
        _energy_sensor("HubA1MeterTotalEnergy", "Meter Total Energy", realtime.get("meterTotalEnergy")),
        _energy_sensor("HubA1DcTotalEnergy", "DC Total Energy", last_alive.get("dcTotalEnergy")),
        _binary_sensor("HubA1AcSwitch", "AC Switch", last_alive.get("acSwitch")),
        _binary_sensor("HubA1DcSwitch", "DC Switch", last_alive.get("dcSwitch")),
        _binary_sensor("HubA1GridSwitch", "Grid Switch", last_alive.get("gridSwitch")),
    ]

    _append_detail_states(states, "HubA1Battery", "Battery", battery_details, include_status=True)
    _append_detail_states(states, "HubA1Pv", "PV", pv_details)
    _append_detail_states(states, "HubA1Load", "Load", load_details)
    _append_detail_states(states, "HubA1Grid", "Grid", grid_details)

    return [state for state in states if state is not None]


def build_app_device_state_overrides(app_device: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Build updates for app-side devices whose HA endpoint returns stale zeros."""
    app_device = app_device or {}
    if not app_device:
        return []
    last_alive = app_device.get("lastAlive") if isinstance(app_device.get("lastAlive"), dict) else {}

    states = [
        _binary_sensor("onLine", "Online", _online_value(app_device, last_alive)),
        _battery_sensor("SOC", "Battery Level", _first(last_alive.get("batterySoc"), app_device.get("batSOC"))),
        _battery_sensor("BatterySoh", "Battery SOH", last_alive.get("batterySoh")),
        _voltage_sensor("BatteryVoltage", "Battery Voltage", last_alive.get("batteryVoltage")),
        _power_sensor("ACLoadAllTotalPower", "Alternating Current Out Power", _first(last_alive.get("powerAcOut"), app_device.get("powerAcOut"))),
        _power_sensor("DCLoadAllTotalPower", "Direct Current Out Power", _first(last_alive.get("powerDcOut"), app_device.get("powerDcOut"))),
        _power_sensor("GridAllTotalPower", "Grid Input Power", _first(last_alive.get("powerGridIn"), app_device.get("powerGridIn"))),
        _power_sensor("PVAllTotalPower", "Photovoltaics Input Power", _first(last_alive.get("powerPvIn"), app_device.get("powerPvIn"))),
        _duration_sensor("ChgFullTime", "Full Charge Time In Minutes", last_alive.get("chgFullTime")),
        _duration_sensor("DsgFullTime", "Battery Time In Minutes", last_alive.get("dsgEmptyTime")),
        _energy_sensor("PackTotalChargeEnergy", "Pack Total Charge Energy", last_alive.get("packTotalChgEnergy")),
        _energy_sensor("PackTotalDischargeEnergy", "Pack Total Discharge Energy", last_alive.get("packTotalDsgEnergy")),
        _energy_sensor("PvTotalEnergy", "PV Total Energy", last_alive.get("pvTotalEnergy")),
        _switch_state("SetCtrlAc", "AC", last_alive.get("acSwitch")),
        _switch_state("SetCtrlDc", "DC", last_alive.get("dcSwitch")),
    ]

    return [state for state in states if state is not None]


def apply_app_device_state_overrides(
    product_data: dict[str, Any],
    app_states: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply app-side state updates to a cached UserProduct-shaped dict."""
    updated_product = dict(product_data)
    state_list = [
        dict(state)
        for state in (updated_product.get("stateList") or [])
        if isinstance(state, dict)
    ]
    states_by_code = {
        state.get("fnCode"): state
        for state in state_list
        if state.get("fnCode")
    }

    for app_state in app_states:
        fn_code = app_state.get("fnCode")
        if not fn_code:
            continue
        if fn_code == "onLine":
            updated_product["online"] = app_state.get("fnValue")
            continue
        existing_state = states_by_code.get(fn_code)
        if existing_state is None:
            new_state = dict(app_state)
            state_list.append(new_state)
            states_by_code[fn_code] = new_state
            continue

        existing_state["fnValue"] = app_state.get("fnValue")
        if not existing_state.get("fnName") and app_state.get("fnName"):
            existing_state["fnName"] = app_state["fnName"]
        if not existing_state.get("fnType") and app_state.get("fnType"):
            existing_state["fnType"] = app_state["fnType"]
        if not existing_state.get("sensorInfo") and app_state.get("sensorInfo"):
            existing_state["sensorInfo"] = app_state["sensorInfo"]
        if not existing_state.get("supportModeValues") and app_state.get("supportModeValues"):
            existing_state["supportModeValues"] = app_state["supportModeValues"]

    updated_product["stateList"] = state_list
    return updated_product


def _append_detail_states(
    states: list[dict[str, Any] | None],
    prefix: str,
    default_label: str,
    rows: list[dict[str, Any]],
    *,
    include_status: bool = False,
) -> None:
    for index, row in enumerate(rows, start=1):
        label = str(row.get("portName") or f"{default_label} {index}").strip()
        states.append(_power_sensor(f"{prefix}{index}Power", f"{label} Power", row.get("power")))
        states.append(_voltage_sensor(f"{prefix}{index}Voltage", f"{label} Voltage", row.get("voltage")))
        if include_status:
            states.append(_plain_sensor(f"{prefix}{index}Status", f"{label} Status", row.get("status")))


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _first_detail_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _is_zero_value(value: Any) -> bool:
    value_text = str(value).strip().lower()
    return value_text in {"0", "0.0", "false", "off"}


def _online_value(app_device: dict[str, Any], last_alive: dict[str, Any]) -> str:
    session_state = str(app_device.get("sessionState") or "").lower()
    if session_state == "online":
        return "1"
    network_connect = app_device.get("networkConnect")
    if str(network_connect) == "1":
        return "1"
    if session_state == "offline":
        return "0"
    if str(network_connect) == "0":
        return "0"
    return "1" if last_alive else "0"


def _redact_identifier_text(value: str) -> str:
    return re.sub(r"\b[A-Z0-9][A-Z0-9_-]{7,}\b", "<redacted>", value)


def _binary_sensor(fn_code: str, fn_name: str, value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    return _state(fn_code, fn_name, "1" if str(value).lower() in {"1", "true", "online"} else "0")


def _battery_sensor(fn_code: str, fn_name: str, value: Any) -> dict[str, Any] | None:
    return _sensor(fn_code, fn_name, value, SENSOR_TYPE_BATTERY, "%")


def _duration_sensor(fn_code: str, fn_name: str, value: Any) -> dict[str, Any] | None:
    return _sensor(fn_code, fn_name, value, "SensorDeviceClass.DURATION", "min")


def _energy_sensor(fn_code: str, fn_name: str, value: Any) -> dict[str, Any] | None:
    return _sensor(fn_code, fn_name, value, SENSOR_TYPE_ENERGY, "kWh")


def _power_sensor(fn_code: str, fn_name: str, value: Any) -> dict[str, Any] | None:
    return _sensor(fn_code, fn_name, value, SENSOR_TYPE_POWER, "W")


def _voltage_sensor(fn_code: str, fn_name: str, value: Any) -> dict[str, Any] | None:
    return _sensor(fn_code, fn_name, value, SENSOR_TYPE_VOLTAGE, "V")


def _plain_sensor(fn_code: str, fn_name: str, value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    return _state(fn_code, fn_name, value)


def _switch_state(fn_code: str, fn_name: str, value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    return _state(fn_code, fn_name, "1" if str(value).lower() in {"1", "true", "online"} else "0", fn_type="SWITCH")


def _sensor(fn_code: str, fn_name: str, value: Any, sensor_type: str, unit: str) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    return _state(fn_code, fn_name, value, {"sensorType": sensor_type, "unit": unit})


def _state(
    fn_code: str,
    fn_name: str,
    value: Any,
    sensor_info: dict[str, str] | None = None,
    fn_type: str = "SENSOR",
) -> dict[str, Any]:
    return {
        "fnCode": fn_code,
        "fnName": fn_name,
        "fnValue": str(value),
        "fnType": fn_type,
        "sensorInfo": sensor_info or {},
        "supportModeValues": [],
    }
