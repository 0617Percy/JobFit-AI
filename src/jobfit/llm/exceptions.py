"""Internal provider failures used to make retry decisions explicit."""

from __future__ import annotations


class ProviderError(Exception):
    """Base provider-boundary failure; never shown directly to users."""


class ProviderAuthenticationError(ProviderError):
    """Credentials are invalid or unauthorized and must not be retried."""


class ProviderTimeoutError(ProviderError):
    """The provider timed out and the request may be retried."""


class ProviderRateLimitError(ProviderError):
    """The provider returned a retryable rate limit response."""


class ProviderServerError(ProviderError):
    """The provider returned a retryable server-side failure."""


class ProviderConnectionError(ProviderError):
    """The provider could not be reached and the request may be retried."""


class ProviderResponseError(ProviderError):
    """A non-retryable provider response could not be interpreted."""


class StrictTransportError(ProviderResponseError):
    """Safe strict-function response failure eligible for semantic retry."""

    def __init__(self, code: str, *, safe_path: str = "transport") -> None:
        self.code = code
        self.safe_path = safe_path
        super().__init__(code)
