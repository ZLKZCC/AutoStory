import os
from urllib.parse import parse_qsl

from starlette.responses import JSONResponse
from starlette.websockets import WebSocketClose

LOOPBACK_HOSTS = ("127.0.0.1", "::1")
ALLOWED_HOSTNAMES = {"localhost", "127.0.0.1", "[::1]"}

def _from_loopback(scope) -> bool:
    client = scope.get("client")
    return bool(client) and client[0] in LOOPBACK_HOSTS

def _host_allowed(scope) -> bool:
    for key, value in scope.get("headers") or []:
        if key == b"host":
            hostname = value.decode("latin-1").rsplit(":", 1)[0].lower()
            return hostname in ALLOWED_HOSTNAMES
    return False

class LoopbackOnlyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            if not _from_loopback(scope) or not _host_allowed(scope):
                if scope["type"] == "http":
                    await JSONResponse(
                        status_code=403, content={"detail": "无授权访问"}
                    )(scope, receive, send)
                else:
                    await WebSocketClose(code=1008)(scope, receive, send)
                return
        await self.app(scope, receive, send)

def _request_token(scope) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == b"x-app-token":
            return value.decode("latin-1")
    query = scope.get("query_string") or b""
    for name, value in parse_qsl(query.decode("latin-1")):
        if name == "token":
            return value
    return None

class AppTokenMiddleware:
    def __init__(self, app):
        self.app = app
        self._token = os.environ.get("AUTOSTORY_APP_TOKEN") or None

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and self._token is not None:
            if _request_token(scope) != self._token:
                if scope["type"] == "http":
                    await JSONResponse(
                        status_code=403, content={"detail": "无效的应用令牌"}
                    )(scope, receive, send)
                else:
                    await WebSocketClose(code=1008)(scope, receive, send)
                return
        await self.app(scope, receive, send)
