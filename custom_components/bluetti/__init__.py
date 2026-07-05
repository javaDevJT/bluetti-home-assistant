"""The BLUETTI integration."""
# from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow, device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import storage

from .models import BluettiData
from .oauth import AsyncConfigEntryAuth,AuthTokenRefresh
from .api.bluetti import APPLICATION_PROFILE
from .api.product_client import ProductClient
from .api.websocket import StompClient
from .hub_a1 import (
    HubA1LookupError,
    apply_app_device_state_overrides,
    is_invalid_hub_a1_product,
    parse_hub_a1_serials,
    summarize_serial_identity,
    summarize_state_values,
)
from .profile.application_profile import ApplicationProfile
from .const import CONF_HUB_A1_SERIALS, DOMAIN
from .model.product import UserProduct

__LOGGER__ = logging.getLogger(__name__)

# TODO List the platforms that you want to support.
# For your initial PR, limit it to 1 platform. Platform.LIGHT,
_PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.SELECT]

# Create ConfigEntry type alias with ConfigEntryAuth or AsyncConfigEntryAuth object
type BluettiConfigEntry = ConfigEntry[BluettiData]


# type Oauth2ConfigEntry = ConfigEntry[api.AsyncConfigEntryAuth]


def _serialize_products(products):
    serialized = []
    for product in products:
        if hasattr(product, "model_dump"):
            serialized.append(product.model_dump())
        elif hasattr(product, "__dict__"):
            serialized.append(product.__dict__)
        else:
            serialized.append(product)
    return serialized


async def _refresh_selected_products(product_client: ProductClient, products: list[UserProduct]) -> list[UserProduct]:
    refreshed_products: list[UserProduct] = []
    for product in products:
        try:
            if product.model == "HA1":
                refreshed_products.append(await product_client.get_hub_a1_product(product.sn))
                continue

            app_states = await product_client.get_app_device_state_overrides(product.sn)
            if app_states:
                product_data = apply_app_device_state_overrides(product.model_dump(), app_states)
                refreshed_products.append(UserProduct.model_validate(product_data))
                continue
        except HubA1LookupError as exc:
            __LOGGER__.warning("Unable to refresh selected Hub A1 device before setup: %s", exc)
        except Exception as exc:
            __LOGGER__.warning(
                "Unable to refresh selected BLUETTI device before setup: %s",
                exc.__class__.__name__,
            )

        refreshed_products.append(product)
    return refreshed_products


def _replace_products_by_sn(products: list[UserProduct], replacements: list[UserProduct]) -> list[UserProduct]:
    replacements_by_sn = {product.sn: product for product in replacements}
    return [replacements_by_sn.get(product.sn, product) for product in products]


async def async_setup_entry(hass: HomeAssistant, entry: BluettiConfigEntry) -> bool:
    await APPLICATION_PROFILE.load_config(hass)

    enabled_devices = entry.options.get("devices", [])
    all_products_data: list[dict] = entry.data.get("products", [])
    all_products: list[UserProduct] = [
        UserProduct.model_validate(p) if isinstance(p, dict) else p
        for p in all_products_data
    ]
    
    """OAUTH2: get the access token."""
    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )
    __LOGGER__.debug("OAuth implementation is: %s", implementation.__class__)

    httpSession = async_get_clientsession(hass)
    oAuth2Session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    # If using a requests-based API lib
    # entry.runtime_data = ConfigEntryAuth(hass, oAuth2Session)

    # If using an aiohttp-based API lib
    entry.runtime_data = AsyncConfigEntryAuth(
        httpSession, oAuth2Session
    )

    authTokenRefresh = AuthTokenRefresh(hass,entry,oAuth2Session)
    authTokenRefresh.start_token_check()
        
    # await oAuth2Session.async_ensure_token_valid()
    access_token = oAuth2Session.token["access_token"]
    product_client = ProductClient(httpSession, access_token,hass)
    # products = await product_client.get_user_products()
    # print(products.data[0].__class__)
    # print(products.data)

    hub_a1_serials = parse_hub_a1_serials(entry.options.get(CONF_HUB_A1_SERIALS))
    invalid_hub_a1_sns = {
        product.sn
        for product in all_products
        if is_invalid_hub_a1_product(product)
    }
    if invalid_hub_a1_sns:
        __LOGGER__.warning(
            "Ignoring invalid cached Hub A1 entries: count=%s targets=%s",
            len(invalid_hub_a1_sns),
            ",".join(summarize_serial_identity(serial) for serial in sorted(invalid_hub_a1_sns)),
        )
        all_products = [
            product
            for product in all_products
            if product.sn not in invalid_hub_a1_sns
        ]
        enabled_devices = [
            serial
            for serial in enabled_devices
            if serial not in invalid_hub_a1_sns
        ]
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, "products": _serialize_products(all_products)},
            options={**entry.options, "devices": enabled_devices, CONF_HUB_A1_SERIALS: hub_a1_serials},
        )

    product_sns = {p.sn for p in all_products}
    products_changed = False
    for serial in hub_a1_serials:
        if serial in product_sns:
            continue
        try:
            product = await product_client.get_hub_a1_product(serial)
        except HubA1LookupError as exc:
            __LOGGER__.warning("Unable to load Hub A1 device through app API: %s", exc)
            continue
        except Exception as exc:
            __LOGGER__.warning("Unable to load Hub A1 device through app API: %s", exc.__class__.__name__)
            continue
        all_products.append(product)
        product_sns.add(product.sn)
        products_changed = True

    if products_changed:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, "products": _serialize_products(all_products)},
        )

    selected_products = await _refresh_selected_products(
        product_client,
        [p for p in all_products if p.sn in enabled_devices],
    )
    all_products = _replace_products_by_sn(all_products, selected_products)
    if selected_products:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, "products": _serialize_products(all_products)},
        )
    for product in selected_products:
        __LOGGER__.warning(
            "BLUETTI setup product summary before entity setup: model=%s %s",
            product.model,
            summarize_state_values(product.stateList or []),
        )

    bluetti_devices = BluettiData(hass, selected_products)

    # Register WebSocket
    stomp_client = StompClient(APPLICATION_PROFILE.config["server"]["wss"], access_token, bluetti_devices.web_socket_message_handler,hass)
    stomp_client.connect()

    for device in bluetti_devices.devices:
        device._api_client = product_client
        device.name = device.sn
        device._hass = hass
        device._entry = entry
        device._entry_id = entry.entry_id

        # device._ws_manager = stomp_client

    async def _async_periodic_refresh(now):
        for device in bluetti_devices.devices:
            try:
                await device.async_update()
            except Exception as exc:
                __LOGGER__.warning(
                    "BLUETTI periodic device refresh failed: model=%s error=%s",
                    device.model,
                    exc.__class__.__name__,
                )
                continue
            __LOGGER__.warning(
                "BLUETTI periodic runtime state summary: model=%s %s",
                device.model,
                summarize_state_values(device.states),
            )

    refresh_unsub = async_track_time_interval(
        hass,
        _async_periodic_refresh,
        timedelta(seconds=60),
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "bluettiDevices": bluetti_devices,
        "stompClient": stomp_client,
        "refresh_unsub": refresh_unsub,
    }

    for device in bluetti_devices.devices:
        try:
            await device.async_update()
        except Exception as exc:
            __LOGGER__.warning(
                "BLUETTI setup initial device refresh failed before entity setup: model=%s error=%s",
                device.model,
                exc.__class__.__name__,
            )
        __LOGGER__.warning(
            "BLUETTI setup runtime state summary before entity setup: model=%s %s",
            device.model,
            summarize_state_values(device.states),
        )

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    # async def _after_start(event):
    #     # print(event)
    #     for device in bluetti_devices.devices:
    #         asyncio.run_coroutine_threadsafe(device.async_update(), hass.loop)

    # hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _after_start)
    __LOGGER__.info('bluetti init ok')

    return True


def web_socket_message_handler(message: str):
    
    __LOGGER__.debug(message)

# TODO Update entry annotation
async def async_unload_entry(hass: HomeAssistant, entry: BluettiConfigEntry) -> bool:
    """Unload a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data:
        refresh_unsub = data.get("refresh_unsub")
        if refresh_unsub:
            refresh_unsub()
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)

async def async_remove_entry(hass, entry):
    """Handle removal of an entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data:
        refresh_unsub = data.get("refresh_unsub")
        if refresh_unsub:
            refresh_unsub()
        if "stompClient" in data:
            stomp_client = data["stompClient"]
            try:
                stomp_client.disconnect()
            except Exception as e:
                __LOGGER__.warning("Error while disconnecting websocket: %s", e)

    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        device_registry.async_remove_device(device.id)

    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        entity_registry.async_remove(entity.entity_id)

    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    store = storage.Store(hass, 1, f"{DOMAIN}_data_{entry.entry_id}.json")
    await store.async_remove()
