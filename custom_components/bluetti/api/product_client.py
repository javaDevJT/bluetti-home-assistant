import logging

import aiohttp

from .bluetti import Bluetti
from .unify_response import UnifyResponse
from ..const import Method
from ..hub_a1 import (
    HubA1LookupError,
    build_app_device_state_overrides,
    build_hub_a1_product_data,
    build_related_hub_a1_fallback_product_data,
    describe_hub_a1_lookup_response,
    has_meaningful_state_values,
    has_hub_a1_telemetry,
    select_hub_a1_related_app_device,
    select_preferred_app_device_payload,
    summarize_payload_values,
    summarize_state_values,
)
from ..model.product import UserProduct


class ProductClient(Bluetti):
    """Class describing for the BLUETTI products."""

    __LOGGER__ = None
    """The api client logger."""

    def __init__(self, httpSession: aiohttp.ClientSession, accessToken,hass):
        super().__init__(httpSession, accessToken,hass)

    @property
    def logger(self) -> logging.Logger:
        """
        Get the api client logger.
        定义API客户端的日志记录器
        """
        if self.__LOGGER__ is None:
            self.__LOGGER__ = logging.getLogger(__name__ + "." + __class__.__name__)
        return self.__LOGGER__

    async def get_user_products(self) -> UnifyResponse[list[UserProduct]]:
        """
        Get user belongs power stations/devices by send an api request.
        请求接口，获取用户所属的发电站/设备信息。
        """
        return await self._request(
            list[UserProduct],
            Method.GET,
            "/api/bluiotdata/ha/v1/devices",
        )

    async def get_device_status(self, sns: str = None) -> UnifyResponse[list[UserProduct]]:
        """
        轮询获取设备状态
        """
        return await self._request(
            list[UserProduct],
            Method.GET,
            "/api/bluiotdata/ha/v1/deviceStates",
            params={'sns': sns}
        )

    async def get_app_device_by_sn(self, device_sn: str) -> UnifyResponse[dict]:
        """Look up a BLUETTI app-side device by serial number."""
        return await self._request(
            dict,
            Method.GET,
            "/api/blusmartprod/device/basic/v1/deviceRemoteSearch",
            params={"deviceSn": device_sn},
        )

    async def get_app_home_devices(self) -> UnifyResponse[list[dict]]:
        """Get app-side home device records."""
        return await self._request(
            list[dict],
            Method.GET,
            "/api/blusmartprod/device/group/v1/homeDevices",
        )

    async def get_app_device_state_overrides(self, device_sn: str) -> list[dict]:
        """Get app-side state updates for devices omitted or stale in HA APIs."""
        app_device = await self._get_app_device_payload(device_sn)
        return build_app_device_state_overrides(app_device)

    async def _get_app_device_payload(self, device_sn: str) -> dict:
        direct_device = {}
        try:
            response = await self.get_app_device_by_sn(device_sn)
        except Exception as exc:
            self.logger.warning("BLUETTI app direct lookup summary: error=%s", exc.__class__.__name__)
        else:
            if response.has_data() and isinstance(response.data, dict) and response.data:
                direct_device = response.data
                self.logger.warning(
                    "BLUETTI app direct lookup summary: status=%s data=%s lastAlive=%s",
                    describe_hub_a1_lookup_response(response),
                    summarize_payload_values(response.data),
                    summarize_payload_values(response.data.get("lastAlive") if isinstance(response.data.get("lastAlive"), dict) else {}),
                )
            else:
                self.logger.warning(
                    "BLUETTI app direct lookup summary: status=%s data=%s",
                    describe_hub_a1_lookup_response(response),
                    summarize_payload_values(response.data),
                )

        home_devices = await self._get_app_home_devices_payload()
        selected = select_preferred_app_device_payload(
            device_sn,
            direct_device,
            home_devices,
            max_age_seconds=900,
        )
        if selected and selected is not direct_device:
            self.logger.warning(
                "BLUETTI app selected home-device payload: data=%s lastAlive=%s",
                summarize_payload_values(selected),
                summarize_payload_values(selected.get("lastAlive") if isinstance(selected.get("lastAlive"), dict) else {}),
            )
        return selected

    async def _get_app_home_devices_payload(self) -> list[dict]:
        try:
            response = await self.get_app_home_devices()
        except Exception as exc:
            self.logger.warning("BLUETTI app home devices summary: error=%s", exc.__class__.__name__)
            return []

        if not response.is_ok() or not isinstance(response.data, list):
            self.logger.warning(
                "BLUETTI app home devices summary: status=%s data=%s",
                describe_hub_a1_lookup_response(response),
                summarize_payload_values(response.data),
            )
            return []

        self.logger.warning(
            "BLUETTI app home devices summary: status=%s data=%s",
            describe_hub_a1_lookup_response(response),
            summarize_payload_values(response.data),
        )
        return response.data

    async def get_aecc_realtime_data(self, device_sn: str) -> UnifyResponse[dict]:
        """Get Hub A1 realtime AECC telemetry."""
        return await self._request(
            dict,
            Method.POST,
            "/api/bluiotdata/aecc/v1/getDeviceRealTimeData",
            body={"deviceSn": device_sn},
        )

    async def get_device_last_alive(self, device_sn: str) -> UnifyResponse[dict]:
        """Get Hub A1 last-alive realtime telemetry."""
        return await self._request(
            dict,
            Method.POST,
            "/api/bluiotdata/realtime/v1/getDeviceLastAlive",
            body={"deviceSn": device_sn},
        )

    async def get_aecc_battery_detail_data(self, device_sn: str) -> UnifyResponse[list[dict]]:
        """Get Hub A1 battery detail telemetry."""
        return await self._request(
            list[dict],
            Method.POST,
            "/api/bluiotdata/aecc/v1/getDeviceBatteryDetailData",
            body={"deviceSn": device_sn},
        )

    async def get_aecc_pv_detail_data(self, device_sn: str) -> UnifyResponse[list[dict]]:
        """Get Hub A1 PV detail telemetry."""
        return await self._request(
            list[dict],
            Method.POST,
            "/api/bluiotdata/aecc/v1/getDevicePvDetailData",
            body={"deviceSn": device_sn},
        )

    async def get_aecc_load_detail_data(self, device_sn: str) -> UnifyResponse[list[dict]]:
        """Get Hub A1 load detail telemetry."""
        return await self._request(
            list[dict],
            Method.POST,
            "/api/bluiotdata/aecc/v1/getDeviceLoadDetailData",
            body={"deviceSn": device_sn},
        )

    async def get_aecc_grid_detail_data(self, device_sn: str) -> UnifyResponse[list[dict]]:
        """Get Hub A1 grid detail telemetry."""
        return await self._request(
            list[dict],
            Method.POST,
            "/api/bluiotdata/aecc/v1/getDeviceGridDetailData",
            body={"deviceSn": device_sn},
        )

    async def get_hub_a1_product(self, device_sn: str) -> UserProduct:
        """Build a UserProduct-shaped Hub A1 object from read-only app APIs."""
        app_device = {}
        app_lookup_status = "not requested"

        try:
            app_device_response = await self.get_app_device_by_sn(device_sn)
        except Exception as exc:
            app_lookup_status = exc.__class__.__name__
        else:
            app_lookup_status = describe_hub_a1_lookup_response(app_device_response)
            if app_device_response.has_data() and isinstance(app_device_response.data, dict) and app_device_response.data:
                app_device = app_device_response.data

        self.logger.warning(
            "Hub A1 app lookup summary: status=%s data=%s lastAlive=%s",
            app_lookup_status,
            summarize_payload_values(app_device),
            summarize_payload_values(app_device.get("lastAlive") if isinstance(app_device.get("lastAlive"), dict) else {}),
        )

        realtime = await self._optional_response_data("realtime", self.get_aecc_realtime_data, device_sn, {})
        last_alive = await self._optional_response_data("lastAlive", self.get_device_last_alive, device_sn, {})
        battery_details = await self._optional_response_data("batteryDetails", self.get_aecc_battery_detail_data, device_sn, [])
        pv_details = await self._optional_response_data("pvDetails", self.get_aecc_pv_detail_data, device_sn, [])
        load_details = await self._optional_response_data("loadDetails", self.get_aecc_load_detail_data, device_sn, [])
        grid_details = await self._optional_response_data("gridDetails", self.get_aecc_grid_detail_data, device_sn, [])

        if not app_device and not has_hub_a1_telemetry(
            realtime=realtime,
            last_alive=last_alive,
            battery_details=battery_details,
            pv_details=pv_details,
            load_details=load_details,
            grid_details=grid_details,
        ):
            raise HubA1LookupError(
                f"Hub A1 lookup returned no app device and no telemetry fallback ({app_lookup_status})"
            )

        product_data = build_hub_a1_product_data(
            device_sn,
            app_device=app_device,
            realtime=realtime,
            last_alive=last_alive,
            battery_details=battery_details,
            pv_details=pv_details,
            load_details=load_details,
            grid_details=grid_details,
        )
        if not has_meaningful_state_values(product_data["stateList"]):
            related_app_device = select_hub_a1_related_app_device(
                await self._get_app_home_devices_payload(),
                max_age_seconds=900,
            )
            related_last_alive = (
                related_app_device.get("lastAlive")
                if isinstance(related_app_device.get("lastAlive"), dict)
                else {}
            )
            if related_app_device and related_last_alive:
                self.logger.warning(
                    "Hub A1 related app telemetry fallback summary: data=%s lastAlive=%s",
                    summarize_payload_values(related_app_device),
                    summarize_payload_values(related_last_alive),
                )
                product_data = build_related_hub_a1_fallback_product_data(
                    device_sn,
                    related_app_device,
                )
        self.logger.warning(
            "Hub A1 built state summary: %s",
            summarize_state_values(product_data["stateList"]),
        )
        return UserProduct.model_validate(product_data)

    async def _optional_response_data(self, label: str, request, device_sn: str, default):
        try:
            response = await request(device_sn)
        except Exception as exc:
            self.logger.warning(
                "Hub A1 optional telemetry summary: endpoint=%s error=%s",
                label,
                exc.__class__.__name__,
            )
            return default
        if not response.is_ok():
            self.logger.warning(
                "Hub A1 optional telemetry summary: endpoint=%s status=%s data=%s",
                label,
                describe_hub_a1_lookup_response(response),
                summarize_payload_values(response.data),
            )
            return default
        data = response.data if response.data is not None else default
        self.logger.warning(
            "Hub A1 optional telemetry summary: endpoint=%s status=%s data=%s",
            label,
            describe_hub_a1_lookup_response(response),
            summarize_payload_values(data),
        )
        return data

    async def control_device(self, payload: str = None):
        """
        控制设备
        """
        return await self._request(
            dict,
            method=Method.POST,
            path="/api/bluiotdata/ha/v1/fulfillment",
            body=payload
        )
    async def bind_devices(self, payload: str = None):
        """
        bind devices
        """
        return await self._request(
            dict,
            method=Method.POST,
            path="/api/bluiotdata/ha/v1/bindDevices",
            body=payload
        )
