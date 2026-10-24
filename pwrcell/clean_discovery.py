"""Backwards-compatibility shim for clean_discovery utility."""

import paho.mqtt.client as mqtt
from .bridge import get_default_published_topics_path
from .tools import clean_discovery as _cd
from .tools.clean_discovery import (
    ORIGIN_INFO,
    is_pwrcell_origin,
    main,
)


def purge_pwrcell_discovery_topics(*args, **kwargs):
    orig_get_cache = _cd.get_default_published_topics_path
    orig_mqtt = _cd.mqtt
    try:
        _cd.get_default_published_topics_path = get_default_published_topics_path
        _cd.mqtt = mqtt
        return _cd.purge_pwrcell_discovery_topics(*args, **kwargs)
    finally:
        _cd.get_default_published_topics_path = orig_get_cache
        _cd.mqtt = orig_mqtt


__all__ = [
    "ORIGIN_INFO",
    "get_default_published_topics_path",
    "is_pwrcell_origin",
    "main",
    "mqtt",
    "purge_pwrcell_discovery_topics",
]

if __name__ == "__main__":
    main()
