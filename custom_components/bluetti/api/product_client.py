import logging

import aiohttp

from .bluetti import Bluetti
from .unify_response import UnifyResponse
from ..const import Method
from ..hub_a1 import (
    HubA1LookupError,
    build_hub_a1_product_data,
    describe_hub_a1_lookup_response,
    has_hub_a1_telemetry,
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

        realtime = await self._optional_response_data(self.get_aecc_realtime_data, device_sn, {})
        last_alive = await self._optional_response_data(self.get_device_last_alive, device_sn, {})
        battery_details = await self._optional_response_data(self.get_aecc_battery_detail_data, device_sn, [])
        pv_details = await self._optional_response_data(self.get_aecc_pv_detail_data, device_sn, [])
        load_details = await self._optional_response_data(self.get_aecc_load_detail_data, device_sn, [])
        grid_details = await self._optional_response_data(self.get_aecc_grid_detail_data, device_sn, [])

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
        return UserProduct.model_validate(product_data)

    async def _optional_response_data(self, request, device_sn: str, default):
        try:
            response = await request(device_sn)
        except Exception as exc:
            self.logger.warning("Optional Hub A1 telemetry request failed: %s", exc.__class__.__name__)
            return default
        if not response.is_ok():
            self.logger.warning("Optional Hub A1 telemetry request returned msgCode=%s", response.msgCode)
            return default
        return response.data if response.data is not None else default

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
