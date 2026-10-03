"""HAAnim: Python automations for Home Assistant.

This package holds the automation engine. The Home Assistant integration in
``custom_components/haanim`` is the glue that connects it to a running instance.

Importing this package does not import Home Assistant.
"""

from haanim.const import ActionMode
from haanim.engine.errors import PUBLIC_ERRORS, HAAnimError

__version__ = "0.1.0"

__all__ = ["ActionMode", "HAAnimError", "PUBLIC_ERRORS", "__version__"]
