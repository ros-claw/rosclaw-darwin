"""Stub for lightwheel_sdk.loader.object_loader.

Returns dummy paths so Arena asset class definitions can execute at
import time without hitting the network.
"""


def acquire_by_registry(registry_type: str, file_name: str | None = None, file_type: str = "USD", **kwargs):
    """Return a dummy local path instead of downloading from Lightwheel."""
    lookup = file_name or kwargs.get("registry_name", ["unknown"])[0]
    dummy_path = f"/tmp/lightwheel_stub/{registry_type}/{lookup}.{file_type.lower()}"
    return dummy_path, lookup, {}
