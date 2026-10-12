"""Home Assistant test fixtures; all external requests are mocked."""

from copy import deepcopy

import pytest

from custom_components.aladdin_connect_cloud.api import parse_doors


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Load the port through Home Assistant's real custom integration loader."""


@pytest.fixture
def devices_payload():
    return deepcopy(
        {
            "devices": [
                {
                    "id": 101,
                    "serial_number": "ABCDEF123456",
                    "name": "Garage controller",
                    "model": "Genie",
                    "software_version": "1.2.3",
                    "ownership": "owned",
                    "is_enabled": True,
                    "doors": [
                        {
                            "id": "ABCDEF123456_1",
                            "door_index": 1,
                            "name": "Main garage",
                            "status": 4,
                            "battery_level": 60,
                            "link_status": 3,
                            "fault": 0,
                            "is_enabled": True,
                        },
                        {
                            "id": "ABCDEF123456_2",
                            "door_index": 2,
                            "name": "Side garage",
                            "status": 1,
                            "battery_level": 0,
                            "link_status": 3,
                            "fault": 0,
                            "is_enabled": True,
                        },
                    ],
                },
                {
                    "id": 202,
                    "serial_number": "112233445566",
                    "ownership": "shared",
                    "doors": [
                        {
                            "id": "112233445566_1",
                            "door_index": 1,
                            "name": "Shared garage",
                            "status": 4,
                            "battery_level": 0,
                            "link_status": 3,
                        }
                    ],
                },
            ],
        }
    )


@pytest.fixture
def doors(devices_payload):
    return parse_doors(devices_payload)
