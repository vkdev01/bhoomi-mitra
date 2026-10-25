"""Domain-level error types.

Adapters translate their own transport-specific failures into these, so the
application layer never has to catch ``httpx`` or ``json`` exceptions. That is
what keeps the dependency arrows pointing inwards.
"""

from __future__ import annotations


class BhoomiError(Exception):
    """Base class for every error this application raises deliberately."""


class PlaceNotFoundError(BhoomiError):
    """The place name could not be resolved to a location."""


class UpstreamAuthError(BhoomiError):
    """The upstream provider rejected our credentials."""


class UpstreamUnavailableError(BhoomiError):
    """The upstream provider failed, timed out, or returned junk."""


class ProviderNotConfiguredError(BhoomiError):
    """A capability was requested that the current wiring cannot serve."""


class ToolInvocationError(BhoomiError):
    """An agent tool was called with unusable arguments or failed internally."""
