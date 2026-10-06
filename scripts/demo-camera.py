#!/usr/bin/env python3
"""Give the demo Home Assistant a camera: ``camera.demo``, a still picture.

The dashboard example shows the picture of ``camera.demo`` on its card. Home
Assistant's ``local_file`` integration makes a camera of a picture file; it is
set up through its configuration flow, which this script walks through as the
container's admin user. A newly built image has the camera already; this is
for a container built before it had. The picture must be in the container::

    podman cp podman/container-config/demo haanim-dev:/config/demo
    uv run python scripts/demo-camera.py

Running it again does nothing: the camera is there.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

import aiohttp

PICTURE = "/config/demo/camera.png"
NAME = "Demo"
ENTITY = "camera.demo"


def smoke_module() -> Any:
    """Load the end-to-end smoke test, whose logged-in connection this script uses."""
    spec = importlib.util.spec_from_file_location("e2e_smoke", Path(__file__).with_name("e2e-smoke.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run(base: str) -> int:
    """Set the camera up unless it is there. Returns the exit code."""
    async with aiohttp.ClientSession() as session:
        smoke = smoke_module().Smoke(session, base)
        await smoke.wait_until_up()
        await smoke.log_in()
        _, states = await smoke.command("get_states")
        if any(state["entity_id"] == ENTITY for state in states):
            print(f"{ENTITY} is there already")
            return 0
        flows = f"{base.rstrip('/')}/api/config/config_entries/flow"
        async with session.post(flows, headers=smoke.headers, json={"handler": "local_file"}) as response:
            flow = await response.json()
        async with session.post(
            f"{flows}/{flow['flow_id']}", headers=smoke.headers, json={"name": NAME, "file_path": PICTURE}
        ) as response:
            result = await response.json()
        if result.get("type") != "create_entry":
            print(f"Could not set up the camera: {result.get('errors') or result}", file=sys.stderr)
            return 1
        print(f"{ENTITY} set up: it shows {PICTURE}")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8123")))
