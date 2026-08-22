"""Desktop `lib/http-status-code.ts`."""

from __future__ import annotations

from enum import IntEnum


class HttpStatusCode(IntEnum):
    """Desktop `HttpStatusCode`."""

    NotModified = 304
    BadRequest = 400
    Unauthorized = 401
    PaymentRequired = 402
    Forbidden = 403
    NotFound = 404
    TooManyRequests = 429
