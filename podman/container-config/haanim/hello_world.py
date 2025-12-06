"""Hello World automation script.

This script demonstrates a simple time-triggered automation
that logs a message every 10 minutes.
"""

import asyncio
import logging
from haanim import action, time_trigger, startup, shutdown, set_status

log = logging.getLogger("haanim.hello_world")


@action("Hello World!")
@time_trigger("cron(*/10 * * * *)")
async def hello_world():
    """Log a hello world message.

    This is a simple demonstration function.
    """
    set_status("Executing Hello World action")
    log.info("Hello World from HAAnim! 🎉")
    log.info("This is a basic automation script.")
    await asyncio.sleep(10)  # Simulate some async work
    set_status("Done sleeping")


@startup
def on_startup():
    """Log a message on startup."""
    log.info("Hello World script has started up!")


@shutdown
def on_shutdown():
    """Log a message on shutdown."""
    log.info("Hello World script is shutting down.")
