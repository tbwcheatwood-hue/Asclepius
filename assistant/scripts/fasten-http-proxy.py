#!/usr/bin/env python3
"""Plain HTTP front for Fasten Health on-prem so the Assistant can embed it.

Fasten serves HTTPS with a private certificate. Browsers will not show that
inside an iframe until the certificate is trusted. This proxy speaks HTTP on
127.0.0.1:9091 and forwards to https://127.0.0.1:9090 without verifying that
certificate. It does not add features or data.
"""
from __future__ import annotations

import http.client
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = ("127.0.0.1", 9090)
LISTEN = ("127.0.0.1", 9091)
HOP = {"transfer-encoding", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else None
        headers = {key: value for key, value in self.headers.items() if key.lower() not in HOP and key.lower() != "host"}
        context = ssl._create_unverified_context()
        connection = http.client.HTTPSConnection(UPSTREAM[0], UPSTREAM[1], context=context, timeout=60)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() in HOP or key.lower() == "content-length":
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        finally:
            connection.close()

    def do_GET(self) -> None:
        self._forward()

    def do_POST(self) -> None:
        self._forward()

    def do_PUT(self) -> None:
        self._forward()

    def do_PATCH(self) -> None:
        self._forward()

    def do_DELETE(self) -> None:
        self._forward()

    def do_OPTIONS(self) -> None:
        self._forward()

    def log_message(self, fmt: str, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
