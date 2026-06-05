"""Monkey-patch lightwheel_sdk to bypass network calls in offline environments."""

import lightwheel_sdk.loader.object

_DUMMY_USD_PATH = "/isaac-sim/kit/resources/models/billboard.usd"


def _patched_acquire_by_registry(self, *args, **kwargs):
    """Return a local dummy USD instead of fetching from remote."""
    return _DUMMY_USD_PATH, "dummy", {}


def _patched_acquire_by_file_version(self, *args, **kwargs):
    return _DUMMY_USD_PATH, "dummy", {}


def _patched_download_to_cache(self, res):
    return _DUMMY_USD_PATH, "dummy"


lightwheel_sdk.loader.object.ObjectLoader.acquire_by_registry = _patched_acquire_by_registry
lightwheel_sdk.loader.object.ObjectLoader.acquire_by_file_version = _patched_acquire_by_file_version
lightwheel_sdk.loader.object.ObjectLoader.download_to_cache = _patched_download_to_cache
