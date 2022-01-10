"""Support for the Roku remote."""
from __future__ import annotations

from homeassistant.components.remote import ATTR_NUM_REPEATS, RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import roku_exception_handler
from .const import DOMAIN
from .coordinator import RokuDataUpdateCoordinator
from .entity import RokuEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load Roku remote based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    unique_id = coordinator.data.info.serial_number
    async_add_entities([RokuRemote(unique_id, coordinator)], True)


class RokuRemote(RokuEntity, RemoteEntity):
    """Device that sends commands to an Roku."""

    def __init__(self, unique_id: str, coordinator: RokuDataUpdateCoordinator) -> None:
        """Initialize the Roku device."""
        super().__init__(
            device_id=unique_id,
            coordinator=coordinator,
        )

        self._attr_name = coordinator.data.info.name
        self._attr_unique_id = unique_id

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return not self.coordinator.data.state.standby

    @roku_exception_handler
    async def async_turn_on(self, **kwargs) -> None:
        """Turn the device on."""
        await self.coordinator.roku.remote("poweron")
        await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_turn_off(self, **kwargs) -> None:
        """Turn the device off."""
        await self.coordinator.roku.remote("poweroff")
        await self.coordinator.async_request_refresh()

    @roku_exception_handler
    async def async_send_command(self, command: list, **kwargs) -> None:
        """Send a command to one device."""
        num_repeats = kwargs[ATTR_NUM_REPEATS]

        for _ in range(num_repeats):
            for single_command in command:
                await self.coordinator.roku.remote(single_command)

        await self.coordinator.async_request_refresh()
