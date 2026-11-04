from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyLimitMiddleware:
    """Bound actual request bytes, including chunked imports, before JSON decoding."""

    def __init__(self, app: ASGIApp, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        messages: list[Message] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                await JSONResponse({"detail": "Request exceeds the import size limit"}, status_code=413)(scope, receive, send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        iterator = iter(messages)

        async def buffered_receive() -> Message:
            try:
                return next(iterator)
            except StopIteration:
                return await receive()

        await self.app(scope, buffered_receive, send)
