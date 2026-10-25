"""RemotePilot Homebrew v1: authenticated, bounded, one-command TCP sessions.

Independent of RP1 and game input. Payloads are authenticated, not encrypted.
Never log wire headers, tokens, addresses or untrusted remote error strings.
"""
import hashlib
import hmac
import ipaddress
import json
from pathlib import Path
import re
import secrets
import socket
import struct
import threading
import time

MAX_CIA = 512 * 1024 * 1024
CHUNK = 65536
TITLE = re.compile(r"00040000[0-9a-f]{8}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
ACTIONS = {"status", "titles", "begin", "chunk", "verify", "install", "cancel", "launch", "job"}
ACTIONS.update({'diag-list','diag-open','diag-read','diag-close'})
ACTIONS.update({'data-begin', 'data-status', 'data-end', 'data-cancel'})


class CompanionRejected(ValueError):
    """An authenticated response explicitly refused the requested command."""
    pass


class CompanionInterrupted(ValueError):
    """Transport interruption only; never an authentication/protocol rejection."""


def private_host(host):
    try:
        address = ipaddress.IPv4Address(host)
    except (ValueError, TypeError):
        raise ValueError("Enter the console's numeric private IPv4 address") from None
    if not any(address in ipaddress.ip_network(net) for net in
               ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")):
        raise ValueError("Console address must be on a private network")
    return str(address)


def title_id(value):
    if not isinstance(value, str) or not TITLE.fullmatch(value.lower()):
        raise ValueError("Only installed SD 3DS application title IDs are supported")
    return value.lower()


def cia_info(path):
    """Inspect bounded CIA/TMD layout before offering a file to the device.

    AM independently checks this metadata and content on the console.
    This parser does not authenticate a publisher or a content signature.
    """
    path = Path(path)
    size = path.stat().st_size
    if not 0x2020 <= size <= MAX_CIA:
        raise ValueError("CIA size is outside the supported range")
    align = lambda n: (n + 63) & ~63
    with path.open("rb") as src:
        header = src.read(32)
        head, kind, _version, cert, ticket, tmd, meta, content = struct.unpack("<IHHIIIIQ", header)
        if head != 0x2020 or kind != 0 or not cert or not ticket or not tmd or not content:
            raise ValueError("Invalid CIA header")
        ticket_at = align(align(head) + cert)
        tmd_at = align(ticket_at + ticket)
        content_at = align(tmd_at + tmd)
        end = align(content_at + content)
        if end > size or end + meta > size or tmd > 1024 * 1024:
            raise ValueError("Truncated CIA layout")
        src.seek(tmd_at)
        signature = {0x10000: 0x240, 0x10003: 0x240, 0x10001: 0x140,
                     0x10004: 0x140, 0x10002: 0x80, 0x10005: 0x80}.get(
                         int.from_bytes(src.read(4), "big"))
        if not signature or signature + 0xc4 + 0x900 + 0x30 > tmd:
            raise ValueError("Invalid CIA title metadata")
        src.seek(tmd_at + signature)
        body = src.read(0xc4)
        ident = title_id(body[0x4c:0x54].hex())
        version = int.from_bytes(body[0x9c:0x9e], "big")
        count = int.from_bytes(body[0x9e:0xa0], "big")
        if not count or signature + 0xc4 + 0x900 + count * 0x30 > tmd:
            raise ValueError("Invalid CIA content table")
    return {"titleId": ident, "version": version, "size": size}


def mac(token, message):
    return hmac.new(bytes.fromhex(token), message.encode("ascii"), hashlib.sha256).hexdigest()


def exact(conn, count):
    body = bytearray()
    while len(body) < count:
        part = conn.recv(min(count - len(body), CHUNK))
        if not part:
            raise CompanionInterrupted("Companion response interrupted; inspect job before retrying")
        body.extend(part)
    return bytes(body)


def line(conn, maximum=256):
    result = bytearray()
    while len(result) < maximum:
        part = exact(conn, 1)
        if part == b"\n":
            return result.decode("ascii")
        result.extend(part)
    raise ValueError("Companion header too long")


class CompanionClient:
    def __init__(self, host, port, token):
        self.host = private_host(host)
        if type(port) is not int or not 1024 <= port <= 65535 or not isinstance(token, str) or not HEX.fullmatch(token):
            raise ValueError("Invalid private companion configuration")
        self.port, self.token = port, token
        # The console handles one connection at a time. Keep status polls from
        # queuing behind a chunk/SD write and consuming each other's deadlines.
        self._io_lock = threading.Lock()

    def call(self, action, payload=b""):
        with self._io_lock:
            # Only reads may retry. Mutations are sent exactly once, then their
            # exact job receipt may be inspected by the deployment worker.
            read_only = action in ('status','titles','job','data-status','diag-list','diag-read')
            deadline = time.monotonic() + 6
            for attempt in range(12 if read_only else 1):
                try:
                    return self._call(action, payload)
                except CompanionInterrupted:
                    if not read_only or attempt == 11 or time.monotonic() >= deadline: raise
                    time.sleep(.12)

    def _call(self, action, payload=b""):
        if action not in ACTIONS or not isinstance(payload, bytes) or len(payload) > CHUNK + 128:
            raise ValueError("Invalid companion request")
        stage = "connecting"
        try:
            with socket.create_connection((self.host, self.port), timeout=2) as conn:
                conn.settimeout(10)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                stage = "authenticating"
                hello = line(conn).split(" ")
                if len(hello) != 4 or hello[:2] != ["RPH1", "CHALLENGE"] or not HEX.fullmatch(hello[2]):
                    raise ValueError("Unexpected companion protocol")
                nonce = hello[2]
                if not hmac.compare_digest(hello[3], mac(self.token, "server:" + nonce)):
                    raise ValueError("Companion pairing proof failed")
                ident = secrets.token_hex(8)
                digest = hashlib.sha256(payload).hexdigest()
                proof = mac(self.token, f"request:{nonce}:{ident}:{action}:{len(payload)}:{digest}")
                conn.sendall(f"RPH1 {ident} {action} {len(payload)} {digest} {proof}\n".encode() + payload)
                # RPH1 carries one exact request per connection. Signal that
                # the request is complete while keeping the response half open.
                # This avoids libctru closing a still-open receive half with RST.
                conn.shutdown(socket.SHUT_WR)
                stage = "waiting-for-acknowledgement"
                header = line(conn).split(" ")
                if len(header) != 5 or header[:2] != ["RPH1", ident] or not header[2].isdigit() \
                        or not HEX.fullmatch(header[3]) or int(header[2]) > 262144:
                    raise ValueError("Invalid companion response")
                length = int(header[2])
                proof = mac(self.token, f"response:{nonce}:{ident}:{length}:{header[3]}")
                if not hmac.compare_digest(header[4], proof):
                    raise ValueError("Companion response proof failed")
                result = exact(conn, length)
                stage = "reading-result"
                if not hmac.compare_digest(hashlib.sha256(result).hexdigest(), header[3]):
                    raise ValueError("Companion response hash mismatch")
                value = json.loads(result)
                if not isinstance(value, dict):
                    raise ValueError("Invalid companion result")
                if value.get("ok") is not True:
                    # Numeric/static error identifiers only; no remote text leaks.
                    error = value.get("error", "declined")
                    if not isinstance(error, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", error):
                        error = "declined"
                    raise CompanionRejected("Companion: " + error)
                return value
        except OSError as exc:
            raise CompanionInterrupted(f"Companion connection interrupted ({stage}, {type(exc).__name__}); inspect job before retrying") from None
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("Companion returned an invalid response; inspect job before retrying") from None

    def data_stream(self, job, offset, source, count):
        """One authenticated connection for up to 4 MiB; never retry a write."""
        if not isinstance(job, str) or not re.fullmatch(r'[0-9a-f]{32}', job) or \
                type(offset) is not int or offset < 0 or type(count) is not int or not 0 < count <= 4 * 1024 * 1024:
            raise ValueError('Invalid fast data window')
        with self._io_lock:
            try:
                with socket.create_connection((self.host, self.port), timeout=2) as conn:
                    conn.settimeout(15)
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    hello = line(conn).split(' ')
                    if len(hello) != 4 or hello[:2] != ['RPH1', 'CHALLENGE'] or not HEX.fullmatch(hello[2]) or \
                            not hmac.compare_digest(hello[3], mac(self.token, 'server:' + hello[2])):
                        raise ValueError('Fast data pairing proof failed')
                    nonce, ident = hello[2], secrets.token_hex(8)
                    body = f'{job} {offset} {count}'.encode('ascii')
                    checksum = hashlib.sha256(body).hexdigest()
                    proof = mac(self.token, f'request:{nonce}:{ident}:data-stream:{len(body)}:{checksum}')
                    conn.sendall(f'RPH1 {ident} data-stream {len(body)} {checksum} {proof}\n'.encode() + body)

                    def reply():
                        header = line(conn).split(' ')
                        if len(header) != 5 or header[:2] != ['RPH1', ident] or not header[2].isdigit() or \
                                not HEX.fullmatch(header[3]) or int(header[2]) > 262144 or \
                                not hmac.compare_digest(header[4], mac(self.token, f'response:{nonce}:{ident}:{header[2]}:{header[3]}')):
                            raise ValueError('Invalid fast data acknowledgement')
                        raw = exact(conn, int(header[2]))
                        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), header[3]):
                            raise ValueError('Fast data response checksum failed')
                        value = json.loads(raw)
                        if not isinstance(value, dict) or value.get('ok') is not True:
                            raise CompanionRejected('Fast data request declined; inspect console status')
                        return value

                    if reply().get('phase') != 'ready':
                        raise ValueError('Console did not accept fast data window')
                    sent = 0
                    while sent < count:
                        block = source.read(min(CHUNK, count - sent))
                        if not block or len(block) > count - sent:
                            raise ValueError('Local data file ended early')
                        digest = hashlib.sha256(block).hexdigest()
                        proof = mac(self.token, f'data:{nonce}:{job}:{offset + sent}:{len(block)}:{digest}')
                        conn.sendall(proof.encode('ascii') + block)
                        sent += len(block)
                    conn.shutdown(socket.SHUT_WR)
                    return reply()
            except OSError as exc:
                raise CompanionInterrupted(f'Fast data transport interrupted ({type(exc).__name__}); inspect exact offset') from None
            except (UnicodeError, json.JSONDecodeError):
                raise ValueError('Invalid fast data response') from None
