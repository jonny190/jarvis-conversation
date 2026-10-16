"""Config flow for the Jarvis Conversation integration."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_API_KEY,
    CONF_FALLBACK_LOCAL,
    CONF_MAX_SPOKEN_CHARS,
    CONF_MODEL,
    CONF_TIMEOUT,
    CONF_URL,
    DEFAULT_FALLBACK_LOCAL,
    DEFAULT_MAX_SPOKEN_CHARS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL, default=DEFAULT_URL): str,
        vol.Required(CONF_API_KEY): str,
        vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): str,
    }
)


def _options_schema(entry: ConfigEntry) -> vol.Schema:
    current = {**entry.data, **entry.options}
    return vol.Schema(
        {
            vol.Required(
                CONF_TIMEOUT, default=current.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=2, max=60, step=0.5, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_FALLBACK_LOCAL,
                default=current.get(CONF_FALLBACK_LOCAL, DEFAULT_FALLBACK_LOCAL),
            ): bool,
            vol.Required(
                CONF_MAX_SPOKEN_CHARS,
                default=current.get(
                    CONF_MAX_SPOKEN_CHARS, DEFAULT_MAX_SPOKEN_CHARS
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=4000, step=50, mode=NumberSelectorMode.BOX
                )
            ),
        }
    )


async def _async_probe(hass, url: str, api_key: str) -> str | None:
    """GET /v1/models. Free: it starts no agent turn and spends nothing."""
    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(10):
            resp = await session.get(
                f"{url.rstrip('/')}/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status == 401:
                return "invalid_auth"
            if resp.status != 200:
                return "cannot_connect"
            await resp.json()
    except (TimeoutError, aiohttp.ClientError, ValueError):
        return "cannot_connect"
    return None


class JarvisConversationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the gateway URL and key, then prove they work."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match({CONF_URL: user_input[CONF_URL]})
            error = await _async_probe(
                self.hass, user_input[CONF_URL], user_input[CONF_API_KEY]
            )
            if error is None:
                return self.async_create_entry(
                    title="Jarvis",
                    data={
                        **user_input,
                        CONF_TIMEOUT: DEFAULT_TIMEOUT,
                        CONF_FALLBACK_LOCAL: DEFAULT_FALLBACK_LOCAL,
                        CONF_MAX_SPOKEN_CHARS: DEFAULT_MAX_SPOKEN_CHARS,
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return JarvisConversationOptionsFlow()


class JarvisConversationOptionsFlow(OptionsFlow):
    """Timeout and fallback behaviour."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(self.config_entry)
        )
