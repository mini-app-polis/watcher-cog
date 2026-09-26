"""watcher-cog package.

Secrets load here, at import, because this runs before any line of the
handler module: ``logger`` reads ``LOG_LEVEL`` and ``config`` reads folder
ids when they are imported, and a secret that arrives after them arrives
too late. With no ``SSM_*`` variables set — a local run, the test suite —
it does nothing.
"""

from mini_app_polis import load_secrets

from ._version import __version__ as __version__

load_secrets()
