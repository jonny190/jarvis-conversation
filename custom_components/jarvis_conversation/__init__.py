"""The Jarvis Conversation integration.

A thin adapter between Home Assistant's Assist pipeline and the Jarvis (hermes-agent)
OpenAI-compatible gateway. It deliberately has no third-party requirements: everything
it needs (aiohttp, voluptuous) already ships inside Home Assistant, so a Home Assistant
upgrade cannot break it the way a shared `openai` pin broke the HACS integration on
14 Oct 2026.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = [Platform.CONVERSATION]

type JarvisConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: JarvisConfigEntry) -> bool:
    """Set up Jarvis Conversation from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JarvisConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: JarvisConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
