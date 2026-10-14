"""Authenticated, single-request LAN transport for optional device presets."""

import hashlib
import hmac
import ipaddress
import re
import secrets
import socket
import time


ID = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
KIND = re.compile(r"[a-z]{1,16}\Z")
CHALLENGE = re.compile(rb"RP2 CHALLENGE ([0-9a-f]{32}) ([0-9a-f]{64})\n\Z")
RESPONSE = re.compile(rb"RP2 RESPONSE ([0-9]{1,10}) ([a-z]{1,16}) ([0-9]{1,8}) ([0-9a-f]{64})\n\Z")
MAX_RESPONSE = {"ping": 0, "meta": 8192, "perf": 2048, "console": 4096,
                "input": 4096, "gamepad": 4096, "touch": 4096,
                "report": 65536, "log": 65536, "shot": 4 * 1024 * 1024,
                "stream": 4 * 1024 * 1024, "preview": 4 * 1024 * 1024,
                "error": 1024}


class TransportError(Exception):
    pass


def private_ipv4(host):
    try:
        address = ipaddress.IPv4Address(host)
    except (ipaddress.AddressValueError, TypeError):
        return False
    return any(address in network for network in (
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.168.0.0/16"),
        ipaddress.IPv4Network("127.0.0.0/8")))


def _read_line(conn, limit, deadline):
    value = bytearray()
    while len(value) < limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransportError("Response timed out")
        conn.settimeout(remaining)
        part = conn.recv(1)
        if not part:
            raise TransportError("Response ended early")
        value.extend(part)
        if part == b"\n":
            return bytes(value)
    raise TransportError("Response line exceeds limit")


def _read_exact(conn, size, deadline):
    value = bytearray()
    while len(value) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransportError("Response timed out")
        conn.settimeout(remaining)
        part = conn.recv(min(8192, size - len(value)))
        if not part:
            raise TransportError("Response body ended early")
        value.extend(part)
    return bytes(value)


def _mac(key, domain, nonce, ident, kind, body):
    prefix = domain + b"\n" + nonce + b"\n" + str(ident).encode() + b"\n" + kind.encode() + b"\n"
    return hmac.new(key, prefix + body, hashlib.sha256).hexdigest().encode()


def exchange(host, port, token_hex, app_id, kind, body=b"", timeout=10):
    """Return authenticated response bytes; each exchange gets a device nonce."""
    if not private_ipv4(host) or type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("A private IPv4 device address and valid port are required")
    if not isinstance(token_hex, str) or not re.fullmatch(r"[0-9a-f]{64}", token_hex):
        raise ValueError("Invalid pairing token")
    if not isinstance(app_id, str) or not ID.fullmatch(app_id) or kind not in MAX_RESPONSE or kind == "error":
        raise ValueError("Invalid application or action")
    if not isinstance(body, bytes) or len(body) > 8192 or not 0 < timeout <= 30:
        raise ValueError("Invalid request size or timeout")
    key = bytes.fromhex(token_hex)
    ident = secrets.randbelow(1_000_000_000)
    try:
        with socket.create_connection((host, port), timeout=min(3, timeout)) as conn:
            deadline = time.monotonic() + timeout
            conn.sendall(f"RP2 HELLO {app_id}\n".encode("ascii"))
            match = CHALLENGE.fullmatch(_read_line(conn, 128, deadline))
            if not match:
                raise TransportError("Invalid device challenge")
            nonce = bytes.fromhex(match.group(1).decode())
            expected = hmac.new(key, b"device\n" + app_id.encode() + b"\n" + nonce, hashlib.sha256).hexdigest().encode()
            if not hmac.compare_digest(match.group(2), expected):
                raise TransportError("Device authentication failed")
            request_mac = _mac(key, b"request", nonce, ident, kind, body)
            conn.sendall(f"RP2 REQUEST {ident} {kind} {len(body)} ".encode() + request_mac + b"\n" + body)
            response = RESPONSE.fullmatch(_read_line(conn, 160, deadline))
            if not response:
                raise TransportError("Invalid response header")
            response_id = int(response.group(1))
            response_kind = response.group(2).decode()
            size = int(response.group(3))
            if response_id != ident or response_kind not in (kind, "error") or size > MAX_RESPONSE[response_kind]:
                raise TransportError("Response ID, action, or size mismatch")
            data = _read_exact(conn, size, deadline)
            response_mac = _mac(key, b"response", nonce, ident, response_kind, data)
            if not hmac.compare_digest(response.group(4), response_mac):
                raise TransportError("Response authentication failed")
            if response_kind == "error":
                raise TransportError("Device declined the action")
            return data
    except (OSError, TimeoutError) as exc:
        raise TransportError("Device unavailable or timed out") from exc
