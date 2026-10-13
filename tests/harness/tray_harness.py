"""Headless test harness for pystray Menu inspection and action invocation."""

from __future__ import annotations

import os
import sys
from typing import Any

if (
    sys.platform not in ("win32", "darwin")
    and not os.environ.get("DISPLAY")
    and not os.environ.get("WAYLAND_DISPLAY")
):
    os.environ.setdefault("PYSTRAY_BACKEND", "dummy")

from pystray import Menu, MenuItem


class HeadlessTrayHarness:
    """Headless driver for inspecting and activating pystray menus without an OS display loop."""

    def __init__(self, menu: Menu, mock_icon: Any = None):
        self.menu = menu
        self.icon = mock_icon

    @property
    def items(self) -> list[MenuItem]:
        """Returns flat list of top-level MenuItems."""
        raw_items: Any = getattr(self.menu, "items", ())
        if isinstance(raw_items, (list, tuple)):
            return [it for it in raw_items if isinstance(it, MenuItem)]
        return []

    def get_labels(self) -> list[str]:
        """Returns the current rendered string labels of all menu items."""
        return [str(item.text) for item in self.items]

    def find_item_by_label(self, label_substring: str) -> MenuItem | None:
        """Finds the first MenuItem whose resolved text contains the substring."""
        for item in self.items:
            if label_substring in str(item.text):
                return item
        return None

    def find_item_by_action(self, action_func: Any) -> MenuItem | None:
        """Finds the first MenuItem whose action matches the function."""
        for item in self.items:
            action = getattr(item, "_action", None)
            if action == action_func or getattr(action, "__wrapped__", None) == action_func:
                return item
        return None

    def invoke(self, item_or_label: MenuItem | str) -> None:
        """Simulates a user clicking a menu item."""
        if isinstance(item_or_label, str):
            item = self.find_item_by_label(item_or_label)
            if item is None:
                raise ValueError(f"Menu item matching '{item_or_label}' not found")
        else:
            item = item_or_label

        item(self.icon)


__all__ = ["HeadlessTrayHarness"]
