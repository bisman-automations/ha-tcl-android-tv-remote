"""Entities keep running when their entity ID is changed (Home Assistant 2026.11+)."""

from __future__ import annotations

import importlib
import pkgutil
from unittest.mock import MagicMock

import pytest

from custom_components import tcl_android_tv_remote
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity

from .conftest import make_entry
from .test_init import MEDIA_PLAYER, _setup

ADD_REMOVE_METHODS = (
    "async_prepare_to_add_to_hass",
    "async_added_to_hass",
    "async_will_remove_from_hass",
)
RENAMED = "media_player.living_room_tv"


def _entity_classes() -> list[type[Entity]]:
    """Every entity class defined in the integration."""
    classes: list[type[Entity]] = []
    for info in pkgutil.walk_packages(
        tcl_android_tv_remote.__path__, f"{tcl_android_tv_remote.__name__}."
    ):
        module = importlib.import_module(info.name)
        classes.extend(
            value
            for value in vars(module).values()
            if isinstance(value, type)
            and issubclass(value, Entity)
            and value.__module__ == module.__name__
        )
    return classes


def test_entities_handle_entity_id_changes() -> None:
    """Every class with its own add or remove code also has the rename hook.

    Home Assistant 2026.11 removes and re-adds an entity whose entity ID
    changes unless the class that defines that code (or a subclass of it)
    defines async_entity_id_changed. A base class's hook doesn't cover it.
    """
    classes = _entity_classes()
    assert classes
    missing = sorted(
        cls.__qualname__
        for cls in classes
        if any(method in cls.__dict__ for method in ADD_REMOVE_METHODS)
        and "async_entity_id_changed" not in cls.__dict__
    )
    assert not missing, f"Missing async_entity_id_changed: {', '.join(missing)}"
    # The hook runs on every supported Home Assistant, with or without the
    # base class's version of it.
    for cls in classes:
        if "async_entity_id_changed" in cls.__dict__:
            cls.async_entity_id_changed(object.__new__(cls), "sensor.old")


@pytest.mark.skipif(
    not hasattr(Entity, "async_entity_id_changed"),
    reason="Entities are changed in place from Home Assistant 2026.11",
)
async def test_renamed_entity_keeps_working(
    hass: HomeAssistant, mock_api: MagicMock
) -> None:
    """A renamed media player moves to its new ID and still follows the TV."""
    await _setup(hass, make_entry())
    assert hass.states.get(MEDIA_PLAYER).state != "off"

    er.async_get(hass).async_update_entity(MEDIA_PLAYER, new_entity_id=RENAMED)
    await hass.async_block_till_done()

    assert hass.states.get(MEDIA_PLAYER) is None
    assert hass.states.get(RENAMED) is not None
    # Changed in place: the TV callbacks were never removed and added again.
    mock_api.remove_is_on_updated_callback.assert_not_called()

    (is_on_updated,) = (
        call.args[0]
        for call in mock_api.add_is_on_updated_callback.call_args_list
        if getattr(call.args[0], "__self__", None) is not None
        and call.args[0].__self__.entity_id == RENAMED
    )
    is_on_updated(False)
    await hass.async_block_till_done()
    assert hass.states.get(RENAMED).state == "off"
    assert hass.states.get(MEDIA_PLAYER) is None
