"""Config flow for TCL Android TV Remote integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any, override

from androidtvremote2 import (
    AndroidTVRemote,
    CannotConnect,
    ConnectionClosed,
    InvalidAuth,
)
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    ADB_MODE_CLASSIC,
    ADB_MODE_TLS,
    ADB_PORT_DISCOVER,
    CONF_ADB_MODE,
    CONF_ADB_PORT,
    CONF_ADB_PORT_DEFAULT,
    CONF_APP_ICON,
    CONF_APP_NAME,
    CONF_APPS,
    CONF_ENABLE_ADB,
    CONF_ENABLE_IME,
    CONF_KEEPALIVE_INTERVAL,
    DEFAULT_TCL_APPS,
    DOMAIN,
    KEEPALIVE_INTERVAL_MAX,
    KEEPALIVE_INTERVAL_MIN,
)
from .helpers import (
    TclAndroidTvRemoteConfigEntry,
    create_adb,
    create_api,
    discover_connect_port,
    discover_pairing_port,
    get_adb_mode,
    get_adb_port,
    get_enable_adb,
    get_enable_ime,
    get_keepalive_interval,
)

_LOGGER = logging.getLogger(__name__)

APPS_NEW_ID = "add_new"
CONF_APP_DELETE = "app_delete"
CONF_APP_ID = "app_id"
CONF_ADD_DEFAULT_APPS = "add_default_apps"
CONF_PAIRING_PORT = "pairing_port"
CONF_PAIRING_CODE = "pairing_code"
CONF_CONNECT_PORT = "connect_port"

_EXAMPLE_APP_ID = "com.plexapp.android"
_EXAMPLE_APP_PLAY_STORE_URL = (
    f"https://play.google.com/store/apps/details?id={_EXAMPLE_APP_ID}"
)

STEP_PAIR_DATA_SCHEMA = vol.Schema({vol.Required("pin"): str})

_PORT_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1024, max=65535, mode=NumberSelectorMode.BOX)
)


def _wireless_schema(discovered_port: int | None, *, with_connect: bool) -> vol.Schema:
    """Form for Wireless debugging pairing (port + code)."""
    fields: dict[Any, Any] = {}
    if with_connect:
        fields[vol.Optional(CONF_CONNECT_PORT)] = _PORT_SELECTOR
    fields[
        vol.Required(
            CONF_PAIRING_PORT,
            description={"suggested_value": discovered_port}
            if discovered_port
            else None,
        )
    ] = _PORT_SELECTOR
    fields[vol.Required(CONF_PAIRING_CODE)] = str
    return vol.Schema(fields)


async def _async_pair_wireless(
    hass: HomeAssistant, host: str, user_input: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    """Pair over Wireless debugging.

    Returns (ADB options to store, error detail). Options are None on failure.
    """
    adb = create_adb(hass, host, ADB_PORT_DISCOVER, use_tls=True)
    ok = await hass.async_add_executor_job(
        adb.pair_wireless,
        int(user_input[CONF_PAIRING_PORT]),
        str(user_input[CONF_PAIRING_CODE]),
    )
    if not ok:
        return None, adb.last_error or "pair failed"
    connect_port = user_input.get(CONF_CONNECT_PORT)
    if not connect_port:
        connect_port = await discover_connect_port(hass, host)
    return (
        {
            CONF_ENABLE_ADB: True,
            CONF_ADB_MODE: ADB_MODE_TLS,
            # Unknown port is fine: the coordinator rediscovers it via mDNS
            CONF_ADB_PORT: int(connect_port) if connect_port else ADB_PORT_DISCOVER,
        },
        "",
    )


class TclAndroidTvRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TCL Android TV Remote."""

    VERSION = 1
    MINOR_VERSION = 2

    api: AndroidTVRemote
    host: str
    name: str
    mac: str

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial and reconfigure step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self.host = user_input[CONF_HOST]
            api = create_api(self.hass, self.host, enable_ime=False)
            await api.async_generate_cert_if_missing()
            try:
                self.name, self.mac = await api.async_get_name_and_mac()
            except CannotConnect:
                # Likely invalid IP address or device is network unreachable. Stay
                # in the user step allowing the user to enter a different host.
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(format_mac(self.mac))
                if self.source == SOURCE_RECONFIGURE:
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(),
                        data={
                            CONF_HOST: self.host,
                            CONF_NAME: self.name,
                            CONF_MAC: self.mac,
                        },
                    )
                self._abort_if_unique_id_configured(updates={CONF_HOST: self.host})
                try:
                    return await self._async_start_pair()
                except (CannotConnect, ConnectionClosed):
                    errors["base"] = "cannot_connect"
        else:
            user_input = {}
        default_host = user_input.get(CONF_HOST, vol.UNDEFINED)
        if self.source == SOURCE_RECONFIGURE:
            default_host = self._get_reconfigure_entry().data[CONF_HOST]
        # pylint: disable-next=home-assistant-step_id-match-method
        return self.async_show_form(
            step_id="reconfigure" if self.source == SOURCE_RECONFIGURE else "user",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=default_host): str}),
            errors=errors,
        )

    async def _async_start_pair(self) -> ConfigFlowResult:
        """Start pairing with the Android TV.

        Navigate to the pair flow to enter the PIN shown on screen.
        """
        self.api = create_api(self.hass, self.host, enable_ime=False)
        await self.api.async_generate_cert_if_missing()
        await self.api.async_start_pairing()
        return await self.async_step_pair()

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the pair step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            pin = user_input["pin"]
            try:
                await self.api.async_finish_pairing(pin)
            except InvalidAuth:
                # Invalid PIN. Stay in the pair step allowing the user to enter
                # a different PIN.
                errors["base"] = "invalid_auth"
            except ConnectionClosed:
                # Either user canceled pairing on the Android TV itself (most common)
                # or device doesn't respond to the specified host (device was unplugged,
                # network was unplugged, or device got a new IP address).
                # Attempt to pair again.
                try:
                    return await self._async_start_pair()
                except (CannotConnect, ConnectionClosed):
                    # Device doesn't respond to the specified host. Abort.
                    # If we are in the user flow we could go back
                    # to the user step to allow them to enter a
                    # new IP address but we cannot do that for the
                    # zeroconf flow. Simpler to abort for both.
                    return self.async_abort(reason="cannot_connect")
            else:
                if self.source == SOURCE_REAUTH:
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), reload_even_if_entry_is_unchanged=True
                    )
                return await self.async_step_adb_setup()
        return self.async_show_form(
            step_id="pair",
            data_schema=STEP_PAIR_DATA_SCHEMA,
            description_placeholders={CONF_NAME: self.name},
            errors=errors,
        )

    async def async_step_adb_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how HDMI control (ADB) connects."""
        return self.async_show_menu(
            step_id="adb_setup",
            menu_options=["adb_wireless", "adb_classic", "adb_none"],
            description_placeholders={CONF_NAME: self.name},
        )

    @callback
    def _create_entry(self, options: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self.name,
            data={CONF_HOST: self.host, CONF_NAME: self.name, CONF_MAC: self.mac},
            options=options,
        )

    async def async_step_adb_wireless(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair Android 11+ Wireless debugging (TLS)."""
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            options, detail = await _async_pair_wireless(
                self.hass, self.host, user_input
            )
            if options is not None:
                return self._create_entry(options)
            errors["base"] = "pair_failed"

        discovered = await discover_pairing_port(self.hass, self.host)
        return self.async_show_form(
            step_id="adb_wireless",
            data_schema=_wireless_schema(discovered, with_connect=True),
            errors=errors,
            description_placeholders={CONF_NAME: self.name, "detail": detail},
        )

    async def async_step_adb_classic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Use classic Network debugging on port 5555."""
        return self._create_entry(
            {
                CONF_ENABLE_ADB: True,
                CONF_ADB_MODE: ADB_MODE_CLASSIC,
                CONF_ADB_PORT: CONF_ADB_PORT_DEFAULT,
            }
        )

    async def async_step_adb_none(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Skip ADB: remote protocol only, no HDMI control."""
        return self._create_entry({CONF_ENABLE_ADB: False})

    @override
    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf discovery."""
        _LOGGER.debug("Android TV device found via zeroconf: %s", discovery_info)
        self.host = discovery_info.host
        self.name = discovery_info.name.removesuffix("._androidtvremote2._tcp.local.")
        if not (mac := discovery_info.properties.get("bt")):
            return self.async_abort(reason="cannot_connect")
        self.mac = mac
        existing_config_entry = await self.async_set_unique_id(format_mac(mac))
        # Sometimes, devices send an invalid zeroconf message with multiple addresses
        # and one of them, which could end up being in discovery_info.host, is from a
        # different device. If any of the discovery_info.ip_addresses matches the
        # existing host, don't update the host.
        if (
            existing_config_entry
            # Ignored entries don't have host
            and CONF_HOST in existing_config_entry.data
            and len(discovery_info.ip_addresses) > 1
        ):
            existing_host = existing_config_entry.data[CONF_HOST]
            if existing_host != self.host and existing_host in [
                str(ip_address) for ip_address in discovery_info.ip_addresses
            ]:
                self.host = existing_host
        # Configured TVs still get IP updates from discovery...
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: self.host, CONF_NAME: self.name}
        )
        # ...but only offer new devices that look like TCL. Every Android TV
        # advertises this service, and core androidtv_remote handles the rest.
        # TCL TVs with a custom name can still be added manually.
        if "tcl" not in self.name.casefold():
            return self.async_abort(reason="not_tcl_device")
        self.context.update({"title_placeholders": {CONF_NAME: self.name}})
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by zeroconf."""
        if user_input is not None:
            try:
                return await self._async_start_pair()
            except (CannotConnect, ConnectionClosed):
                # Device became network unreachable after discovery.
                # Abort and let discovery find it again later.
                return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={CONF_NAME: self.name},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle configuration by re-auth."""
        self.host = entry_data[CONF_HOST]
        self.name = entry_data[CONF_NAME]
        self.mac = entry_data[CONF_MAC]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                return await self._async_start_pair()
            except (CannotConnect, ConnectionClosed):
                # Device is network unreachable. Abort.
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={CONF_NAME: self.name},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        return await self.async_step_user(user_input)

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: TclAndroidTvRemoteConfigEntry,
    ) -> TclAndroidTvRemoteOptionsFlowHandler:
        """Create the options flow."""
        return TclAndroidTvRemoteOptionsFlowHandler(config_entry)


class TclAndroidTvRemoteOptionsFlowHandler(OptionsFlowWithReload):
    """TCL Android TV Remote options flow.

    A menu of independent sections; each one saves (and reloads) on submit.
    """

    def __init__(self, config_entry: TclAndroidTvRemoteConfigEntry) -> None:
        """Initialize options flow."""
        self._apps: dict[str, Any] = dict(config_entry.options.get(CONF_APPS, {}))
        self._conf_app_id: str | None = None

    @callback
    def _save(self, changes: dict[str, Any]) -> ConfigFlowResult:
        """Merge changes into the current options and save."""
        data = {**self.config_entry.options, **changes}
        if self._apps:
            data[CONF_APPS] = self._apps
        else:
            data.pop(CONF_APPS, None)
        return self.async_create_entry(data=data)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Options menu."""
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "apps", "adb_pair"]
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """General and ADB settings."""
        entry = self.config_entry
        if user_input is not None:
            changes = dict(user_input)
            if changes.get(CONF_ADB_MODE) == ADB_MODE_CLASSIC and not changes.get(
                CONF_ADB_PORT
            ):
                changes[CONF_ADB_PORT] = CONF_ADB_PORT_DEFAULT
            changes[CONF_ADB_PORT] = int(changes.get(CONF_ADB_PORT) or 0)
            changes[CONF_KEEPALIVE_INTERVAL] = int(changes[CONF_KEEPALIVE_INTERVAL])
            return self._save(changes)

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENABLE_IME, default=get_enable_ime(entry)): bool,
                    vol.Required(CONF_ENABLE_ADB, default=get_enable_adb(entry)): bool,
                    vol.Required(
                        CONF_ADB_MODE, default=get_adb_mode(entry)
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[ADB_MODE_TLS, ADB_MODE_CLASSIC],
                            mode=SelectSelectorMode.LIST,
                            translation_key="adb_mode",
                        )
                    ),
                    vol.Optional(
                        CONF_ADB_PORT,
                        description={"suggested_value": get_adb_port(entry) or None},
                    ): _PORT_SELECTOR,
                    vol.Required(
                        CONF_KEEPALIVE_INTERVAL, default=get_keepalive_interval(entry)
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=KEEPALIVE_INTERVAL_MIN,
                            max=KEEPALIVE_INTERVAL_MAX,
                            step=5,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

    async def async_step_apps(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick an app to edit, add one, or add the TCL / Google TV presets."""
        if user_input is not None:
            if user_input.get(CONF_ADD_DEFAULT_APPS):
                for package, name in DEFAULT_TCL_APPS.items():
                    self._apps.setdefault(
                        package, {CONF_APP_NAME: name, CONF_APP_ICON: ""}
                    )
                if not user_input.get(CONF_APPS):
                    return self._save({})
            if sel_app := user_input.get(CONF_APPS):
                self._conf_app_id = None if sel_app == APPS_NEW_ID else sel_app
                return self._async_app_form(sel_app)
            return self._save({})

        apps = [SelectOptionDict(value=APPS_NEW_ID, label="Add new")] + [
            SelectOptionDict(
                value=k, label=f"{v[CONF_APP_NAME]} ({k})" if v.get(CONF_APP_NAME) else k
            )
            for k, v in self._apps.items()
        ]
        return self.async_show_form(
            step_id="apps",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_APPS): SelectSelector(
                        SelectSelectorConfig(
                            options=apps,
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="apps",
                        )
                    ),
                    # Off by default so presets you deleted don't come back
                    vol.Optional(CONF_ADD_DEFAULT_APPS, default=False): bool,
                }
            ),
        )

    async def async_step_app(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit, add or delete a single app."""
        if user_input is not None:
            app_id = user_input.get(CONF_APP_ID, self._conf_app_id)
            if app_id:
                if user_input.get(CONF_APP_DELETE, False):
                    self._apps.pop(app_id, None)
                else:
                    self._apps[app_id] = {
                        CONF_APP_NAME: user_input.get(CONF_APP_NAME, ""),
                        CONF_APP_ICON: user_input.get(CONF_APP_ICON, ""),
                    }
        return self._save({})

    @callback
    def _async_app_form(self, app_id: str) -> ConfigFlowResult:
        """Return configuration form for one app."""
        current = self._apps.get(app_id, {})
        app_schema: dict[Any, Any] = {
            vol.Optional(
                CONF_APP_NAME,
                description={"suggested_value": current.get(CONF_APP_NAME, "")},
            ): str,
            vol.Optional(
                CONF_APP_ICON,
                description={"suggested_value": current.get(CONF_APP_ICON, "")},
            ): str,
        }
        if app_id == APPS_NEW_ID:
            data_schema = vol.Schema({**app_schema, vol.Required(CONF_APP_ID): str})
        else:
            data_schema = vol.Schema(
                {**app_schema, vol.Optional(CONF_APP_DELETE, default=False): bool}
            )
        return self.async_show_form(
            step_id="app",
            data_schema=data_schema,
            description_placeholders={
                "app_id": f"`{app_id}`" if app_id != APPS_NEW_ID else "",
                "example_app_id": _EXAMPLE_APP_ID,
                "example_app_play_store_url": _EXAMPLE_APP_PLAY_STORE_URL,
            },
        )

    async def async_step_adb_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """(Re-)pair Android 11+ Wireless debugging and switch to it."""
        entry = self.config_entry
        host = entry.data[CONF_HOST]
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            options, detail = await _async_pair_wireless(self.hass, host, user_input)
            if options is not None:
                return self._save(options)
            errors["base"] = "pair_failed"

        discovered = await discover_pairing_port(self.hass, host)
        return self.async_show_form(
            step_id="adb_pair",
            data_schema=_wireless_schema(discovered, with_connect=True),
            errors=errors,
            description_placeholders={CONF_NAME: entry.title, "detail": detail},
        )
