"""Fixtures for Home Assistant-level tests (needs pytest-homeassistant-custom-component)."""

import sys
from pathlib import Path

import pytest

# Make `custom_components.infomentor` importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
	"""Allow HA to load the integration from custom_components/."""
	yield
