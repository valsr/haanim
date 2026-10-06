#!/usr/bin/env python3
"""End-to-end smoke test against the development container.

Start the container (``./build-and-run.sh``), then run::

    uv run python scripts/e2e-smoke.py [http://localhost:8123]

It logs in as the container's admin user and checks, in a real Home Assistant,
that the example automations are loaded and running, that their entities,
services, websocket commands, assets and frontend modules are there, and that
an automation's card and log follow what the automation does.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import aiohttp

USERNAME = "admin"
PASSWORD = "admin"
EXAMPLES = ("climate", "dashboard", "motion_light")
STARTUP_SECONDS = 180


class Smoke:
    """A logged-in connection to Home Assistant, over HTTP and over the websocket."""

    def __init__(self, session: aiohttp.ClientSession, base: str) -> None:
        self._session = session
        self._base = base.rstrip("/")
        self._token = ""
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._next_id = 0
        self._events: dict[int, list[dict[str, Any]]] = {}

    async def wait_until_up(self) -> None:
        """Wait until Home Assistant answers."""
        for _ in range(STARTUP_SECONDS):
            try:
                async with self._session.get(f"{self._base}/manifest.json") as response:
                    if response.status == 200:
                        return
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(1)
        raise AssertionError(f"Home Assistant did not come up at {self._base}")

    async def log_in(self) -> None:
        """Get an access token for the admin user and open the websocket."""
        client = {"client_id": f"{self._base}/", "redirect_uri": f"{self._base}/"}
        async with self._session.post(
            f"{self._base}/auth/login_flow", json={**client, "handler": ["homeassistant", None]}
        ) as response:
            flow = await response.json()
        async with self._session.post(
            f"{self._base}/auth/login_flow/{flow['flow_id']}",
            json={"client_id": client["client_id"], "username": USERNAME, "password": PASSWORD},
        ) as response:
            result = await response.json()
        assert result.get("type") == "create_entry", f"login failed: {result}"
        async with self._session.post(
            f"{self._base}/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": result["result"],
                "client_id": client["client_id"],
            },
        ) as response:
            self._token = (await response.json())["access_token"]

        self._socket = await self._session.ws_connect(f"{self._base}/api/websocket")
        assert (await self._socket.receive_json())["type"] == "auth_required"
        await self._socket.send_json({"type": "auth", "access_token": self._token})
        assert (await self._socket.receive_json())["type"] == "auth_ok"

    @property
    def headers(self) -> dict[str, str]:
        """The headers of a logged-in request."""
        return {"Authorization": f"Bearer {self._token}"}

    async def command(self, kind: str, **data: Any) -> tuple[int, Any]:
        """Send a websocket command; return its ID and its result."""
        assert self._socket is not None
        self._next_id += 1
        command_id = self._next_id
        await self._socket.send_json({"id": command_id, "type": kind, **data})
        while True:
            message = await asyncio.wait_for(self._socket.receive_json(), 30)
            if message.get("type") == "event":
                self._events.setdefault(message["id"], []).append(message["event"])
            elif message.get("id") == command_id:
                assert message.get("success"), f"{kind} failed: {message.get('error')}"
                return command_id, message.get("result")

    async def event(self, subscription: int, wanted: Any, what: str) -> dict[str, Any]:
        """Return the first event of a subscription for which ``wanted`` is true, waiting for it if needed."""
        assert self._socket is not None
        seen = self._events.setdefault(subscription, [])
        for _ in range(200):
            while seen:
                event = seen.pop(0)
                if wanted(event):
                    return event
            try:
                message = await asyncio.wait_for(self._socket.receive_json(), 15)
            except TimeoutError:
                break
            if message.get("type") == "event":
                self._events.setdefault(message["id"], []).append(message["event"])
        raise AssertionError(f"did not see {what}")

    async def service(self, domain: str, service: str, response: bool = False, **data: Any) -> Any:
        """Call a service; return its response data if asked for."""
        _, result = await self.command(
            "call_service", domain=domain, service=service, service_data=data, return_response=response
        )
        return (result or {}).get("response")

    async def get(self, path: str, logged_in: bool = True) -> tuple[int, str, str]:
        """GET a path; return status, content type and body."""
        async with self._session.get(
            f"{self._base}{path}", headers=self.headers if logged_in else {}
        ) as response:
            return response.status, response.content_type, await response.text()


def check(condition: Any, what: str) -> None:
    """Report one check; stop at the first that fails."""
    print(f"{'ok  ' if condition else 'FAIL'} {what}")
    if not condition:
        raise AssertionError(what)


async def automations(smoke: Smoke) -> dict[str, dict[str, Any]]:
    """Return the automations by ID."""
    _, result = await smoke.command("haanim/automations/list")
    return {automation["id"]: automation for automation in result["automations"]}


async def run(base: str) -> None:
    """Run every check."""
    async with aiohttp.ClientSession() as session:
        smoke = Smoke(session, base)
        await smoke.wait_until_up()
        await smoke.log_in()
        check(True, "Home Assistant is up and the admin user can log in")

        # --- The examples are loaded and running ------------------------------------------
        found: dict[str, dict[str, Any]] = {}
        for _ in range(STARTUP_SECONDS):
            try:
                found = await automations(smoke)
            except AssertionError:
                found = {}
            if all(found.get(name, {}).get("state") == "on" for name in EXAMPLES):
                break
            await asyncio.sleep(1)
        for name in EXAMPLES:
            state = found.get(name, {})
            check(
                state.get("state") == "on",
                f"automation {name} is on ({state.get('message') or 'no message'})",
            )
        check(found["climate"]["name"] == "Climate", "the name comes from metadata.json")

        # --- Entities ------------------------------------------------------------------------
        _, states = await smoke.command("get_states")
        by_id = {state["entity_id"]: state for state in states}
        for name in EXAMPLES:
            entity = by_id.get(f"sensor.haanim_{name}")
            check(entity is not None and entity["state"] == "on", f"entity sensor.haanim_{name} is on")
        attributes = by_id["sensor.haanim_dashboard"]["attributes"]
        check(
            attributes["device_class"] == "enum" and attributes["enabled"] is True,
            "the entity has its attributes",
        )

        # --- Services ------------------------------------------------------------------------
        listed = await smoke.service("haanim", "list_automations", True)
        check(
            sorted(item["id"] for item in listed["automations"]) == sorted(EXAMPLES),
            "haanim.list_automations",
        )
        actions = await smoke.service("haanim", "list_actions", True, automation_id="dashboard")
        check({"count", "reset"} <= {action["name"] for action in actions["actions"]}, "haanim.list_actions")

        # --- The card follows the automation ---------------------------------------------------
        await smoke.service("haanim", "run_action", automation_id="dashboard", action="reset")
        card, _ = await smoke.command("haanim/card/subscribe", automation_id="dashboard")
        first = await smoke.event(card, lambda event: "blocks" in event, "the card of the dashboard example")
        ids = [block["id"] for block in first["blocks"]]
        check(
            ids == ["intro", "logo", "count", "uptime", "sun", "add", "reset", "frame"],
            f"the card has its blocks: {ids}",
        )
        check(
            first["title"] == "Dashboard demo", f"the card has the title the automation set: {first['title']}"
        )

        logs, _ = await smoke.command("haanim/logs/subscribe", automation_id="dashboard")
        await smoke.event(logs, lambda event: "records" in event, "the recent log records")

        result = await smoke.service(
            "haanim", "run_action", True, automation_id="dashboard", action="count", data={"step": 2}
        )
        check(result == {"result": 2}, f"haanim.run_action returns the action's result: {result}")

        def count_is(value: int) -> Any:
            return lambda event: any(
                block["id"] == "count" and block["value"] == value for block in event["blocks"]
            )

        updated = await smoke.event(card, count_is(2), "the count on the card after the action")
        check(True, "the card is updated over the websocket when the action changes it")
        check(updated["title"] == "Dashboard demo: 2 pressed", f"the title follows: {updated['title']}")
        await smoke.event(
            logs, lambda event: event.get("record", {}).get("message") == "Counted to 2", "the log"
        )
        check(True, "what the action printed arrives as a log record")

        await smoke.service("haanim", "run_action", automation_id="dashboard", action="toggle_frame")
        bare = await smoke.event(card, lambda event: not event["options"]["title"], "the stripped card")
        check(not any(bare["options"].values()), "the automation can hide every fixed part of its card")
        await smoke.service("haanim", "run_action", automation_id="dashboard", action="toggle_frame")
        await smoke.event(card, lambda event: event["options"]["title"], "the card with its frame again")

        await smoke.command("fire_event", event_type="dashboard_count", event_data={"step": 3})
        await smoke.event(card, count_is(5), "the count on the card after the event")
        check(True, "an event trigger fires and the card follows")

        # --- A state trigger, a service call from the automation, persistent storage ------------
        await smoke.service("input_number", "set_value", entity_id="input_number.temperature", value=25)
        await asyncio.sleep(1)
        await smoke.service("input_number", "set_value", entity_id="input_number.temperature", value=31)
        detail: dict[str, Any] = {}
        for _ in range(30):
            _, detail = await smoke.command("haanim/automations/get", automation_id="climate")
            if detail["last_action"] == "high_temperature_alert" and not detail["running_actions"]:
                break
            await asyncio.sleep(0.5)
        check(
            detail["last_action"] == "high_temperature_alert",
            "the state trigger of the climate example fired",
        )
        check(detail["last_error"] is None, f"its action finished without an error: {detail['last_error']}")
        await smoke.service("input_number", "set_value", entity_id="input_number.temperature", value=21)

        # --- Assets and the frontend -----------------------------------------------------------
        status, content_type, body = await smoke.get("/api/haanim/assets/dashboard/logo.svg")
        check(
            status == 200 and "svg" in content_type and "<svg" in body,
            "the asset is served to a logged-in user",
        )
        status, _, _ = await smoke.get("/api/haanim/assets/dashboard/logo.svg", logged_in=False)
        check(status == 401, "the asset is refused without login")
        status, _, _ = await smoke.get("/api/haanim/assets/dashboard/..%2Fmain.py")
        check(status in (400, 404), "the automation's code is not served as an asset")
        for module in ("haanim-panel.js", "haanim-card.js", "haanim-render.js"):
            status, _, body = await smoke.get(f"/haanim/ui/{module}", logged_in=False)
            check(status == 200 and "haanim" in body, f"the frontend module {module} is served")
        _, panels = await smoke.command("get_panels")
        check("haanim" in panels, "the HAAnim panel is registered")
        _, config = await smoke.command("haanim/config/get")
        check(config["options"]["max_concurrent_actions"] == 20, "the configuration is readable")

        # --- Control -----------------------------------------------------------------------------
        await smoke.service("haanim", "stop", automation_id="dashboard")
        await smoke.event(card, lambda event: event["blocks"] == [], "the empty card after the stop")
        check((await automations(smoke))["dashboard"]["state"] == "off", "haanim.stop stops the automation")
        await smoke.service("haanim", "start", automation_id="dashboard")
        await smoke.event(card, count_is(5), "the card after the restart")
        check(True, "after a restart the card is rebuilt, with the stored count")

    print("\nEnd-to-end smoke test passed")


if __name__ == "__main__":
    try:
        asyncio.run(run(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8123"))
    except AssertionError as failure:
        print(f"\nEnd-to-end smoke test FAILED: {failure}", file=sys.stderr)
        sys.exit(1)
