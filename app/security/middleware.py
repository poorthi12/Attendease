from collections.abc import Awaitable, Callable

ASGIApp = Callable[[dict, Callable, Callable], Awaitable[None]]


class RequestLimitsAndHeaders:
    """Bound form request bodies and add basic browser security headers."""

    def __init__(self, app: ASGIApp, max_body_bytes: int = 1_048_576):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        if method in {"POST", "PUT", "PATCH"}:
            headers = dict(scope.get("headers", []))
            content_length = headers.get(b"content-length")
            if content_length:
                try:
                    too_large = int(content_length) > self.max_body_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    await self._too_large(send)
                    return

            received = 0

            async def limited_receive():
                nonlocal received
                message = await receive()
                if message.get("type") == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.max_body_bytes:
                        raise _BodyTooLarge
                return message

            async def secure_send(message: dict) -> None:
                if message.get("type") == "http.response.start":
                    current = list(message.get("headers", []))
                    present = {key.lower() for key, _ in current}
                    security_headers = [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    ]
                    current.extend((key, value) for key, value in security_headers if key not in present)
                    message["headers"] = current
                await send(message)

            try:
                await self.app(scope, limited_receive, secure_send)
            except _BodyTooLarge:
                await self._too_large(secure_send)
            return

        async def secure_send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                current = list(message.get("headers", []))
                present = {key.lower() for key, _ in current}
                current.extend((key, value) for key, value in [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                ] if key not in present)
                message["headers"] = current
            await send(message)

        await self.app(scope, receive, secure_send)

    async def _too_large(self, send: Callable) -> None:
        body = b"Request is too large."
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass
