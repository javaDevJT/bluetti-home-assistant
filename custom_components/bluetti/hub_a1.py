"""Hub A1 helpers for BLUETTI app API payloads."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any


HUB_A1_MODEL = "HA1"

SENSOR_TYPE_BATTERY = "SensorDeviceClass.BATTERY"
SENSOR_TYPE_ENERGY = "SensorDeviceClass.ENERGY"
SENSOR_TYPE_POWER = "SensorDeviceClass.POWER"
SENSOR_TYPE_VOLTAGE = "SensorDeviceClass.VOLTAGE"

TELEMETRY_KEYS = {
    "acswitch",
    "batsoc",
    "batterysoc",
    "batterysoh",
    "batteryvoltage",
    "battoloadpower",
    "chgfulltime",
    "currentforbms",
    "dcswitch",
    "dctotalenergy",
    "dsgemptytime",
    "frequency",
    "gridbatpower",
    "gridswitch",
    "gridtoloadpower",
    "metertotalenergy",
    "packaveragetemp",
    "packtotalchgenergy",
    "packtotaldsgenergy",
    "power",
    "poweracout",
    "powerbatterycharge",
    "powerdcout",
    "powerfeedback",
    "powergridin",
    "powerinvtotal",
    "powerloadout",
    "powerpvin",
    "pvswitch",
    "pvtobatpower",
    "pvtogridpower",
    "pvtotalenergy",
    "voltage",
}

RELATED_HUB_A1_FALLBACK_KEYS = {
    "acSwitch",
    "dcSwitch",
    "dcTotalEnergy",
    "gridSwitch",
    "powerLoadOut",
    "powerAcOut",
    "powerDcOut",
    "powerGridIn",
    "powerPvIn",
    "timestamp",
}

RELATED_HUB_A1_SYSTEM_FALLBACK_KEYS = {
    "batterySoc",
    "batterySoh",
    "batteryVoltage",
    "meterTotalEnergy",
    "powerBatteryCharge",
}


class HubA1LookupError(RuntimeError):
    """Raised when a Hub A1 cannot be resolved from app or telemetry APIs."""


def parse_hub_a1_serials(value: Any) -> list[str]:
    """Parse a comma/whitespace separated Hub A1 serial field."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value]
    else:
        parts = [part.strip() for part in re.split(r"[\r\n,;]+", str(value))]

    serials: list[str] = []
    for part in parts:
        if is_hub_a1_serial_candidate(part) and part not in serials:
            serials.append(part)
    return serials


def is_hub_a1_serial_candidate(value: Any) -> bool:
    """Return true for values that look like serials rather than names/models."""
    if value is None:
        return False
    value_text = str(value).strip()
    if len(value_text) < 8 or len(value_text) > 64:
        return False
    if any(char.isspace() for char in value_text):
        return False
    serial_text = value_text.replace("-", "").replace("_", "")
    return serial_text.isalnum() and any(char.isalpha() for char in serial_text) and any(
        char.isdigit() for char in serial_text
    )


def is_invalid_hub_a1_product(product: Any) -> bool:
    """Return true for cached HA1 products whose sn is not a serial."""
    if isinstance(product, dict):
        model = product.get("model")
        serial = product.get("sn")
    else:
        model = getattr(product, "model", None)
        serial = getattr(product, "sn", None)
    return str(model or "").upper() == HUB_A1_MODEL and not is_hub_a1_serial_candidate(serial)


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
        _telemetry_payload_score(value) > 0
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


def has_meaningful_state_values(states: list[Any]) -> bool:
    """Return true when states contain nonzero values other than online."""
    for state in states:
        if isinstance(state, dict):
            fn_code = state.get("fnCode")
            value = state.get("fnValue")
        else:
            fn_code = getattr(state, "fn_code", None)
            value = getattr(state, "fn_value", None)
        if not fn_code or str(fn_code) == "onLine":
            continue
        value_text = "" if value is None else str(value)
        if value_text != "" and not _is_zero_value(value_text):
            return True
    return False


def summarize_payload_values(payload: Any, *, limit: int = 6) -> str:
    """Return a serial-safe summary of API payload scalar values."""
    row_count = len(payload) if isinstance(payload, list) else None
    field_count = 0
    zero = 0
    nonzero = 0
    empty = 0
    samples: list[str] = []

    for key, value in _iter_payload_scalars(payload):
        field_count += 1
        value_text = "" if value is None else str(value)
        if value_text == "":
            empty += 1
            continue
        if _is_zero_value(value_text):
            zero += 1
            continue

        nonzero += 1
        if len(samples) < limit and not _is_identifier_key(key):
            safe_key = _redact_identifier_text(key)
            safe_value = _redact_identifier_text(value_text)
            samples.append(f"{safe_key}={safe_value}")

    parts = []
    if row_count is not None:
        parts.append(f"rows={row_count}")
    parts.extend(
        [
            f"fields={field_count}",
            f"nonzero={nonzero}",
            f"zero={zero}",
            f"empty={empty}",
            f"samples={','.join(samples) if samples else 'none'}",
        ]
    )
    return " ".join(parts)


def summarize_hub_a1_field_sources(
    *,
    app_device: dict[str, Any] | None = None,
    realtime: dict[str, Any] | None = None,
    last_alive: dict[str, Any] | None = None,
    battery_details: list[dict[str, Any]] | None = None,
) -> str:
    """Return a concise summary of the source selected for key HA1 fields."""
    app_device = app_device or {}
    realtime = realtime or {}
    last_alive = last_alive or {}
    battery_details = battery_details or []

    fields = [
        (
            "BatterySoc",
            [
                ("lastAlive.batterySoc", last_alive.get("batterySoc")),
                ("realtime.batterySoc", realtime.get("batterySoc")),
                ("app.batSOC", app_device.get("batSOC")),
            ],
        ),
        (
            "BatteryVoltage",
            [
                ("lastAlive.batteryVoltage", last_alive.get("batteryVoltage")),
                ("batteryDetails.voltage", _first_detail_value(battery_details, "voltage")),
            ],
        ),
        (
            "AcPowerOut",
            [
                ("realtime.powerLoadOut", realtime.get("powerLoadOut")),
                ("lastAlive.powerLoadOut", last_alive.get("powerLoadOut")),
                ("lastAlive.powerAcOut", last_alive.get("powerAcOut")),
                ("app.powerAcOut", app_device.get("powerAcOut")),
            ],
        ),
        (
            "GridPowerIn",
            [
                ("realtime.powerGridIn", realtime.get("powerGridIn")),
                ("lastAlive.powerGridIn", last_alive.get("powerGridIn")),
                ("lastAlive.powerFeedBack", last_alive.get("powerFeedBack")),
                ("app.powerGridIn", app_device.get("powerGridIn")),
            ],
        ),
        (
            "InverterTotalPower",
            [
                ("lastAlive.powerInvTotal", last_alive.get("powerInvTotal")),
            ],
        ),
        (
            "PvPowerIn",
            [
                ("realtime.powerPvIn", realtime.get("powerPvIn")),
                ("lastAlive.powerPvIn", last_alive.get("powerPvIn")),
                ("app.powerPvIn", app_device.get("powerPvIn")),
            ],
        ),
        (
            "DcPowerOut",
            [
                ("lastAlive.powerDcOut", last_alive.get("powerDcOut")),
                ("app.powerDcOut", app_device.get("powerDcOut")),
            ],
        ),
        (
            "BatteryChargePower",
            [
                ("realtime.powerBatteryCharge", realtime.get("powerBatteryCharge")),
                ("lastAlive.powerBatteryCharge", last_alive.get("powerBatteryCharge")),
            ],
        ),
        (
            "MeterTotalEnergy",
            [
                ("realtime.meterTotalEnergy", realtime.get("meterTotalEnergy")),
                ("lastAlive.meterTotalEnergy", last_alive.get("meterTotalEnergy")),
            ],
        ),
    ]

    summaries = [_selected_source_summary(name, sources) for name, sources in fields]
    summaries.append(
        _selected_source_summary(
            "BatteryTotalChargeEnergy",
            [("lastAlive.packTotalChgEnergy", last_alive.get("packTotalChgEnergy"))],
        )
    )
    summaries.append(
        _ignored_source_summary(
            "PackTotalDischargeEnergy",
            "lastAlive.packTotalDsgEnergy",
            last_alive.get("packTotalDsgEnergy"),
            "ignored_displayed_as_charge",
        )
    )
    return ",".join(summaries)


def _selected_source_summary(field_name: str, sources: list[tuple[str, Any]]) -> str:
    first_present: tuple[str, Any] | None = None
    for label, value in sources:
        if value is None or value == "":
            continue
        if first_present is None:
            first_present = (label, value)
        if not _is_zero_value(value):
            safe_value = _redact_identifier_text(str(value))
            return f"{field_name}={label}:{safe_value}"
    if first_present is None:
        return f"{field_name}=none"
    label, value = first_present
    safe_value = _redact_identifier_text(str(value))
    return f"{field_name}=zero:{label}:{safe_value}"


def _ignored_source_summary(
    field_name: str,
    label: str,
    value: Any,
    reason: str,
) -> str:
    if value is None or value == "":
        return f"{field_name}=none"
    safe_value = _redact_identifier_text(str(value))
    return f"{field_name}={reason}:{label}:{safe_value}"


def summarize_serial_identity(value: Any) -> str:
    """Return a stable, non-reversible serial summary for log correlation."""
    if value is None:
        return "empty"
    value_text = str(value).strip()
    if not value_text:
        return "empty"
    digest = hashlib.sha256(value_text.encode("utf-8")).hexdigest()[:16]
    return f"len={len(value_text)} sha256={digest}"


def summarize_app_home_device_serials(
    target_serial: Any,
    home_devices: list[dict[str, Any]] | None,
    *,
    limit: int = 6,
) -> str:
    """Summarize app home-device serials without exposing identifiers."""
    target_text = _normalize_serial_text(target_serial)
    device_count = 0
    matches = 0
    samples: list[str] = []

    for item in home_devices or []:
        if not isinstance(item, dict):
            continue
        device_count += 1
        item_serial = _payload_serial_value(item)
        item_serial_text = _normalize_serial_text(item_serial)
        if target_text and item_serial_text == target_text:
            matches += 1
        if len(samples) < limit:
            model = _redact_identifier_text(str(item.get("model") or "unknown"))
            identity = summarize_serial_identity(item_serial) if item_serial_text else "missing"
            samples.append(f"{model}:{identity}")

    return (
        f"target={summarize_serial_identity(target_serial)} "
        f"home_devices={device_count} matches={matches} "
        f"samples={','.join(samples) if samples else 'none'}"
    )


def app_device_telemetry_score(app_device: dict[str, Any] | None) -> int:
    """Return a rough score for useful app-side telemetry in a device payload."""
    if not isinstance(app_device, dict) or not app_device:
        return 0

    top_level = {
        key: value
        for key, value in app_device.items()
        if key != "lastAlive"
    }
    score = _telemetry_payload_score(top_level)
    last_alive = app_device.get("lastAlive")
    if isinstance(last_alive, dict) and not _is_all_field_null(last_alive):
        score += 3 * _telemetry_payload_score(last_alive)
    return score


def select_preferred_app_device_payload(
    device_sn: str,
    direct_device: dict[str, Any] | None,
    home_devices: list[dict[str, Any]] | None,
    *,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Select the richest app-side payload for a specific device serial."""
    direct_device = direct_device or {}
    home_match = {}
    for item in home_devices or []:
        if (
            isinstance(item, dict)
            and item.get("sn") == device_sn
            and _is_recent_app_device_telemetry(
                item,
                now=now,
                max_age_seconds=max_age_seconds,
            )
        ):
            home_match = item
            break

    if not direct_device:
        return home_match
    if not home_match:
        return direct_device

    if app_device_telemetry_score(home_match) > app_device_telemetry_score(direct_device):
        return home_match
    return direct_device


def select_hub_a1_related_app_device(
    home_devices: list[dict[str, Any]] | None,
    *,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Select an Apex-family app device whose telemetry can represent a Hub A1."""
    candidates = []
    for item in home_devices or []:
        if not isinstance(item, dict):
            continue
        if not _is_recent_app_device_telemetry(
            item,
            now=now,
            max_age_seconds=max_age_seconds,
        ):
            continue
        telemetry_score = app_device_telemetry_score(item)
        model_score = _hub_related_model_score(item.get("model"))
        if telemetry_score > 0 and model_score > 0:
            candidates.append((model_score, telemetry_score, item))
    if not candidates:
        return {}
    return max(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]


def build_related_hub_a1_fallback_product_data(
    serial: str,
    related_app_device: dict[str, Any],
) -> dict[str, Any]:
    """Build HA1 fallback states from related app telemetry without battery identity."""
    related_last_alive = related_app_device.get("lastAlive")
    if not isinstance(related_last_alive, dict):
        related_last_alive = {}
    fallback_keys = RELATED_HUB_A1_FALLBACK_KEYS
    if _is_hub_related_system_model(related_app_device.get("model")):
        fallback_keys = fallback_keys | RELATED_HUB_A1_SYSTEM_FALLBACK_KEYS
    fallback_last_alive = {
        key: value
        for key, value in related_last_alive.items()
        if key in fallback_keys
    }
    fallback_app_device = {
        "model": HUB_A1_MODEL,
        "networkConnect": related_app_device.get("networkConnect"),
        "sessionState": related_app_device.get("sessionState"),
        "powerAcOut": related_app_device.get("powerAcOut"),
        "powerDcOut": related_app_device.get("powerDcOut"),
        "powerGridIn": related_app_device.get("powerGridIn"),
        "powerPvIn": related_app_device.get("powerPvIn"),
    }
    return build_hub_a1_product_data(
        serial,
        app_device=fallback_app_device,
        last_alive=fallback_last_alive,
    )


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
    battery_total_charge_energy = _centi_kwh_value(last_alive.get("packTotalChgEnergy"))

    states = [
        _binary_sensor("onLine", "Online", _online_value(app_device, last_alive)),
        _battery_sensor("HubA1BatterySoc", "Battery SOC", _first_nonzero(last_alive.get("batterySoc"), realtime.get("batterySoc"), app_device.get("batSOC"))),
        _voltage_sensor(
            "HubA1BatteryVoltage",
            "Battery Voltage",
            _first(last_alive.get("batteryVoltage"), _first_detail_value(battery_details, "voltage")),
        ),
        _power_sensor("HubA1AcPowerOut", "AC Output Power", _first_nonzero(realtime.get("powerLoadOut"), last_alive.get("powerLoadOut"), last_alive.get("powerAcOut"), app_device.get("powerAcOut"))),
        _power_sensor("HubA1DcPowerOut", "DC Output Power", _first_nonzero(last_alive.get("powerDcOut"), app_device.get("powerDcOut"))),
        _power_sensor("HubA1GridPowerIn", "Grid Input Power", _first_nonzero(realtime.get("powerGridIn"), last_alive.get("powerGridIn"), last_alive.get("powerFeedBack"), app_device.get("powerGridIn"))),
        _power_sensor("HubA1PvPowerIn", "PV Input Power", _first_nonzero(realtime.get("powerPvIn"), last_alive.get("powerPvIn"), app_device.get("powerPvIn"))),
        _power_sensor("HubA1BatteryChargePower", "Battery Charge Power", _first_nonzero(realtime.get("powerBatteryCharge"), last_alive.get("powerBatteryCharge"))),
        _energy_sensor("HubA1DcTotalEnergy", "DC Total Energy", last_alive.get("dcTotalEnergy")),
        _energy_sensor("HubA1PackTotalChargeEnergy", "Battery Total Charge Energy", battery_total_charge_energy),
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
        if not _has_nonzero_detail_state(row, include_status=include_status):
            continue
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


def _first_nonzero(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "" and not _is_zero_value(value):
            return value
    return _first(*values)


def _first_detail_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _is_zero_value(value: Any) -> bool:
    value_text = str(value).strip().lower()
    if value_text in {"false", "off"}:
        return True
    try:
        return float(value_text) == 0
    except ValueError:
        return False


def _centi_kwh_value(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        scaled_value = float(str(value).strip()) / 100
    except ValueError:
        return None
    return f"{scaled_value:.2f}"


def _has_nonzero_detail_state(row: dict[str, Any], *, include_status: bool) -> bool:
    keys = ["power", "voltage"]
    if include_status:
        keys.append("status")
    return any(
        row.get(key) is not None
        and row.get(key) != ""
        and not _is_zero_value(row.get(key))
        for key in keys
    )


def _telemetry_payload_score(payload: Any) -> int:
    score = 0
    for key, value in _iter_payload_scalars(payload):
        value_text = "" if value is None else str(value)
        if value_text == "" or _is_zero_value(value_text):
            continue
        key_name = key.rsplit(".", 1)[-1].lower()
        if key_name in TELEMETRY_KEYS:
            score += 1
    return score


def _is_all_field_null(payload: dict[str, Any]) -> bool:
    return str(payload.get("allFieldIsNull")).strip().lower() == "true"


def _is_recent_app_device_telemetry(
    app_device: dict[str, Any],
    *,
    now: datetime | None,
    max_age_seconds: int | None,
) -> bool:
    if max_age_seconds is None:
        return True
    last_alive = app_device.get("lastAlive")
    if not isinstance(last_alive, dict):
        return False
    timestamp = _parse_bluetti_timestamp(last_alive.get("timestamp"))
    if timestamp is None:
        return False
    if now is None:
        now = datetime.now()
    age_seconds = (now - timestamp).total_seconds()
    return age_seconds <= max_age_seconds


def _parse_bluetti_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    value_text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value_text[:19], fmt)
        except ValueError:
            continue
    return None


def _hub_related_model_score(model: Any) -> int:
    model_text = str(model or "").upper()
    if _is_hub_related_system_model(model):
        return 120
    if "EL100" in model_text:
        return 100
    if "HA1" in model_text:
        return 90
    return 0


def _is_hub_related_system_model(model: Any) -> bool:
    model_text = str(model or "").upper()
    return any(marker in model_text for marker in ("APEX", "AP300"))


def _iter_payload_scalars(payload: Any, prefix: str = ""):
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            nested_key = f"{prefix}.{key_text}" if prefix else key_text
            yield from _iter_payload_scalars(value, nested_key)
        return
    if isinstance(payload, list):
        for index, item in enumerate(payload, start=1):
            item_prefix = _payload_row_prefix(item, index, prefix)
            yield from _iter_payload_scalars(item, item_prefix)
        return
    if prefix:
        yield prefix, payload


def _payload_row_prefix(item: Any, index: int, prefix: str) -> str:
    label = None
    if isinstance(item, dict):
        for key in ("portName", "name", "moduleName"):
            value = item.get(key)
            if value:
                label = _redact_identifier_text(str(value))
                break
    row_name = label or f"row{index}"
    return f"{prefix}.{row_name}" if prefix else row_name


def _payload_serial_value(payload: dict[str, Any]) -> Any:
    for key in ("sn", "deviceSn", "deviceSN", "boardSn", "mesSn", "serial"):
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None


def _normalize_serial_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _is_identifier_key(key: str) -> bool:
    key_parts = {part.lower() for part in re.split(r"[^A-Za-z0-9]+", key) if part}
    if key_parts & {"sn", "id", "mac", "uuid"}:
        return True
    return any(
        marker in part
        for part in key_parts
        for marker in ("serial", "devicesn", "deviceid")
    )


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


def _energy_sensor(fn_code: str, fn_name: str, value: Any, *, unit: str = "kWh") -> dict[str, Any] | None:
    return _sensor(fn_code, fn_name, value, SENSOR_TYPE_ENERGY, unit)


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
