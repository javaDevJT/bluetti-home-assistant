"""Hub A1 helpers for BLUETTI app API payloads."""

from __future__ import annotations

import re
from typing import Any


HUB_A1_MODEL = "HA1"

SENSOR_TYPE_BATTERY = "SensorDeviceClass.BATTERY"
SENSOR_TYPE_ENERGY = "SensorDeviceClass.ENERGY"
SENSOR_TYPE_POWER = "SensorDeviceClass.POWER"
SENSOR_TYPE_VOLTAGE = "SensorDeviceClass.VOLTAGE"


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
        _power_sensor("HubA1AcPowerOut", "AC Output Power", _first(app_device.get("powerAcOut"), realtime.get("powerLoadOut"))),
        _power_sensor("HubA1DcPowerOut", "DC Output Power", app_device.get("powerDcOut")),
        _power_sensor("HubA1GridPowerIn", "Grid Input Power", _first(app_device.get("powerGridIn"), realtime.get("powerGridIn"))),
        _power_sensor("HubA1PvPowerIn", "PV Input Power", _first(app_device.get("powerPvIn"), realtime.get("powerPvIn"))),
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


def _online_value(app_device: dict[str, Any], last_alive: dict[str, Any]) -> str:
    session_state = str(app_device.get("sessionState") or "").lower()
    if session_state == "online":
        return "1"
    if session_state == "offline":
        return "0"
    network_connect = app_device.get("networkConnect")
    if str(network_connect) == "1":
        return "1"
    if str(network_connect) == "0":
        return "0"
    return "1" if last_alive else "0"


def _binary_sensor(fn_code: str, fn_name: str, value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    return _state(fn_code, fn_name, "1" if str(value).lower() in {"1", "true", "online"} else "0")


def _battery_sensor(fn_code: str, fn_name: str, value: Any) -> dict[str, Any] | None:
    return _sensor(fn_code, fn_name, value, SENSOR_TYPE_BATTERY, "%")


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


def _sensor(fn_code: str, fn_name: str, value: Any, sensor_type: str, unit: str) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    return _state(fn_code, fn_name, value, {"sensorType": sensor_type, "unit": unit})


def _state(
    fn_code: str,
    fn_name: str,
    value: Any,
    sensor_info: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "fnCode": fn_code,
        "fnName": fn_name,
        "fnValue": str(value),
        "fnType": "SENSOR",
        "sensorInfo": sensor_info or {},
        "supportModeValues": [],
    }
