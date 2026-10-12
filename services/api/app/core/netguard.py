"""Outbound request containment.

The moment a user can name an arbitrary URL for Prism to call, Prism becomes a
server-side request forgery engine pointed at its own infrastructure. This
module is the control that prevents that, and it is deliberately separate,
small and testable, because a vulnerability here would be in a security product.

What it refuses, and why:

* **Private, loopback, link-local and reserved address space.** Cloud instance
  metadata lives at 169.254.169.254, databases at 10.x, and a request to
  127.0.0.1 reaches Prism itself. None of these is ever a legitimate target.
* **Every resolved address, not just the first.** A hostname with one public
  and one private A record would otherwise pass a naive check and connect to
  the private one.
* **Non-HTTPS schemes.** No file://, gopher://, or plain http to a public host.
* **Credentials, ports and fragments in the URL.** `user:pass@host` and
  non-standard ports are rejected rather than silently normalised.

What it does NOT do, stated plainly so nobody assumes otherwise:

* It cannot prevent DNS rebinding on its own. The address checked at validation
  time may differ from the one connected to later. Mitigating that fully
  requires pinning the resolved address at connect time, which belongs in the
  HTTP client, not here. The short window and the per-connection allowlist
  reduce but do not eliminate it.
* It does not prove the caller owns the target. That is an authorisation
  question, not a network one. See `ownership` in the connection model.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

# Ranges that must never be reachable from a user-supplied endpoint.
_BLOCKED_V4 = [
    ipaddress.ip_network("0.0.0.0/8"),        # "this host"
    ipaddress.ip_network("10.0.0.0/8"),       # private
    ipaddress.ip_network("100.64.0.0/10"),    # carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),      # loopback -- reaches Prism itself
    ipaddress.ip_network("169.254.0.0/16"),   # link-local, incl. cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),    # private
    ipaddress.ip_network("192.0.0.0/24"),     # IETF protocol assignments
    ipaddress.ip_network("192.168.0.0/16"),   # private
    ipaddress.ip_network("198.18.0.0/15"),    # benchmarking
    ipaddress.ip_network("224.0.0.0/4"),      # multicast
    ipaddress.ip_network("240.0.0.0/4"),      # reserved
]
_BLOCKED_V6 = [
    ipaddress.ip_network("::/128"),           # unspecified
    ipaddress.ip_network("::1/128"),          # loopback
    ipaddress.ip_network("fc00::/7"),         # unique local
    ipaddress.ip_network("fe80::/10"),        # link-local
    ipaddress.ip_network("ff00::/8"),         # multicast
    ipaddress.ip_network("::ffff:0:0/96"),    # IPv4-mapped: check the v4 inside
]

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TIMEOUT_MS = 300_000


class EndpointRejected(ValueError):
    """The endpoint is not permitted. The message is safe to show a user."""


@dataclass(frozen=True)
class CheckedEndpoint:
    url: str
    host: str
    addresses: tuple[str, ...]


def _address_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    nets = _BLOCKED_V4 if ip.version == 4 else _BLOCKED_V6
    for net in nets:
        if ip in net:
            return str(net)
    # Belt and braces: the stdlib's own classification, for anything missed.
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return "reserved or private address space"
    return None


def resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise EndpointRejected(f"Host '{host}' could not be resolved: {exc.strerror or exc}.")
    seen: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.append(addr)
    if not seen:
        raise EndpointRejected(f"Host '{host}' resolved to no addresses.")
    return seen


def check_endpoint(url: str, *, allow_insecure_localhost: bool = False) -> CheckedEndpoint:
    """Validate a user-supplied endpoint, or raise `EndpointRejected`.

    `allow_insecure_localhost` exists only for local development against a
    service on the same machine. It is never enabled in a deployed
    configuration.
    """
    if not url or not url.strip():
        raise EndpointRejected("An endpoint URL is required.")
    url = url.strip()

    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise EndpointRejected(
            f"Scheme '{parsed.scheme or 'none'}' is not allowed. Use https."
        )
    if parsed.username or parsed.password:
        raise EndpointRejected("Credentials embedded in the URL are not allowed.")
    if parsed.fragment:
        raise EndpointRejected("A URL fragment is not allowed on an endpoint.")
    host = parsed.hostname
    if not host:
        raise EndpointRejected("The endpoint URL has no host.")

    is_localhost = host in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme == "http" and not (allow_insecure_localhost and is_localhost):
        raise EndpointRejected(
            "Plain http is not allowed for a remote endpoint. Use https, so the "
            "credential and the prompts are not sent in clear text."
        )
    if is_localhost:
        if not allow_insecure_localhost:
            raise EndpointRejected(
                "localhost is not a reachable target for a deployed evaluation."
            )
        return CheckedEndpoint(url=url, host=host, addresses=(host,))

    if parsed.port is not None and parsed.port not in (80, 443):
        raise EndpointRejected(
            f"Port {parsed.port} is not allowed. Use the default https port."
        )

    addresses = resolve(host)
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise EndpointRejected(f"Host '{host}' resolved to an unusable address.")
        # EVERY address must be acceptable. One public and one private record
        # would otherwise let a naive check through to the private one.
        blocked = _address_is_blocked(ip)
        if blocked:
            raise EndpointRejected(
                f"Host '{host}' resolves to {addr}, which is inside {blocked}. "
                f"Prism will not send requests into private or reserved address "
                f"space."
            )
    return CheckedEndpoint(url=url, host=host, addresses=tuple(addresses))


def check_against_allowlist(url: str, allowed_hosts: set[str]) -> CheckedEndpoint:
    """Containment plus the project's declared allowlist.

    Both must pass. The allowlist expresses intent ("this is the host I meant
    to test"); the containment check expresses safety ("and it is not inside
    our network"). Neither substitutes for the other.
    """
    checked = check_endpoint(url)
    if allowed_hosts and checked.host.lower() not in {h.lower() for h in allowed_hosts}:
        raise EndpointRejected(
            f"Endpoint host '{checked.host}' is not in the allowlist. Add it "
            f"deliberately before testing against it."
        )
    return checked
