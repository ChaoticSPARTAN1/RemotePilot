"""Public HTTPS downloads: verified TLS, pinned DNS, no environment proxies."""
import http.client
import ipaddress
import socket
from urllib.request import HTTPSHandler


def public_address(value):
    address = ipaddress.ip_address(value)
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not address.is_unspecified and not address.is_loopback
            and not address.is_link_local and not getattr(address, 'ipv4_mapped', None))


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        if self._tunnel_host:
            raise ValueError('HTTPS proxy tunnels are disabled for CIA downloads')
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not addresses or len(addresses) > 16 or any(not public_address(item[4][0]) for item in addresses):
            raise ValueError('CIA URL must resolve only to public Internet addresses')
        last_error = None
        for address in addresses:
            try:
                # A numeric address prevents a second hostname lookup/rebinding;
                # TLS SNI and certificate checks still use the original hostname.
                raw = socket.create_connection((address[4][0], self.port), self.timeout, self.source_address)
            except OSError as exc:
                last_error = exc
                continue
            try:
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                return
            except Exception:
                raw.close()
                raise
        raise last_error or OSError('No reachable public HTTPS address')


class PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(PublicHTTPSConnection, request, context=self._context)
