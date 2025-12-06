"""Hello World automation script.

This script demonstrates a simple time-triggered automation
that logs a message every 10 minutes.
"""

# from haanim import action, time_trigger


# @time_trigger("cron(*/10 * * * *)")
# @action("Hello World Logger")
# def hello_world():
#     """Log a hello world message every 10 minutes.

#     This is a simple demonstration of a time-triggered automation.
#     The cron expression "*/10 * * * *" means "every 10 minutes".
#     """
#     log.info("Hello World from HAAnim! 🎉")
#     log.info("This message appears every 10 minutes.")

import logging
from haanim import action, time_trigger

log = logging.getLogger("haanim.hello_world")


@action("Hello World!")
@time_trigger("cron(*/10 * * * *)")
def hello_world():
    """Log a hello world message.

    This is a simple demonstration function.
    """
    log.info("Hello World from HAAnim! 🎉")
    log.info("This is a basic automation script.")
