"""Domain-specific Redfish exceptions for centralized error handling.

Services and the MCP server should catch `RedfishError` to avoid crashing
the process when Redfish endpoints return errors or the network has issues.
"""

class RedfishError(Exception):
    """Base class for all Redfish-related errors."""
    pass


class RedfishNotFound(RedfishError):
    """Raised when the remote resource returns HTTP 404."""
    pass


class RedfishUnauthorized(RedfishError):
    """Raised when the remote endpoint returns 401/403."""
    pass


class RedfishClientError(RedfishError):
    """Raised for other 4xx client errors."""
    pass


class RedfishServerError(RedfishError):
    """Raised for 5xx server errors."""
    pass


class RedfishTimeout(RedfishError):
    """Raised for network timeouts."""
    pass


class RedfishConnectionError(RedfishError):
    """Raised for general connection errors."""
    pass


class RedfishJSONError(RedfishError):
    """Raised when JSON parsing/decoding fails for an expected JSON response."""
    pass


class RedfishTransientError(RedfishError):
    """Marker for errors that are transient and may be retried."""
    pass
