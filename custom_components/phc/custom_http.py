"""The PHC STM does not give valid HTTP responses. This is a workaround for that."""

import asyncio


class RawTCPResponse:
    """TCP Response."""

    def __init__(self, status_code, headers, body) -> None:
        """Init the TCPResponse. Headers will have faulty removed."""
        self.status = status_code
        self.headers = headers
        self._body = body

    @property
    def content(self):
        """Content of the respone."""
        return self._body.decode(errors="replace")


class RawTCPClientSession:
    """Http implementation that allows faulty headers."""

    def __init__(self, host, port=None) -> None:
        """Init the RawTCPClientSession with a host and a port."""
        # Parse host:port if combined string is given
        if ":" in host and port is None:
            parts = host.rsplit(":", 1)
            self.host = parts[0]
            self.port = int(parts[1])
        else:
            self.host = host
            self.port = port or 80

        self._reader = None
        self._writer = None

    async def __aenter__(self):
        """ASYNC ENTRY."""
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """ASYNC EXIT."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()

    async def _request(self, method, path, headers=None, data=None):
        reader, writer = await asyncio.open_connection(self.host, self.port)

        request_lines = [
            f"{method} {path} HTTP/1.1",
            f"Host: {self.host}"
            + (f":{self.port}" if self.port not in (80, 443) else ""),
            "Connection: close",
        ]
        if headers:
            for k, v in headers.items():
                request_lines.append(f"{k}: {v}")

        if data:
            body = data.encode() if isinstance(data, str) else data
            request_lines.append(f"Content-Length: {len(body)}")
        else:
            body = b""

        request_lines.append("")  # End headers
        request_lines.append("")  # Blank line after headers

        request_message = "\r\n".join(request_lines).encode() + body

        writer.write(request_message)
        await writer.drain()

        # Read status line
        status_line = await reader.readline()
        parts = status_line.decode().split()
        status_code = int(parts[1]) if len(parts) >= 2 else 0

        # Read headers
        headers = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            if b":" in line:
                key, val = line.decode().split(":", 1)
                headers[key.strip()] = val.strip()
            else:
                # Ignore malformed header lines gracefully
                pass

        # Read body until EOF
        body_bytes = await reader.read()

        writer.close()
        await writer.wait_closed()

        return RawTCPResponse(status_code, headers, body_bytes)

    async def get(self, path="/", headers=None):
        """Make a get request."""
        return await self._request("GET", path, headers)

    async def post(self, path="/", headers=None, data=None):
        """Make a post request."""
        return await self._request("POST", path, headers, data)
