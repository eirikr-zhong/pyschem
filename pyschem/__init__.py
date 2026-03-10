"""Compatibility shim for package name `pyschem`.

Primary source currently lives in `lib`.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pyschem")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"  # fallback when not installed

from lib import *  # noqa: F401,F403
