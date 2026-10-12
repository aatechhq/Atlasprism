"""Proof that the caller controls the host they want to test.

Containment (`netguard`) answers "is this address safe to reach". This module
answers the different and equally necessary question: **is the caller allowed
to point adversarial tests at it.**

A checkbox is not authorisation. Shield sends prompt-injection and
secret-extraction attempts, so a user must demonstrate control of the host
before Prism will send anything there. Two standard methods, both requiring
access a random stranger does not have:

1. **DNS TXT** — publish the token at `_atlas-prism.<host>`. Proves control of
   the domain's DNS.
2. **HTTPS file** — serve the token at
   `https://<host>/.well-known/atlas-prism-verification.txt`. Proves control of
   the web server.

DNS is resolved over DNS-over-HTTPS rather than the system resolver: it needs
no new dependency, works identically inside a container, and is not affected by
whatever the host's `/etc/resolv.conf` happens to say.

The file method reuses `netguard` before fetching, so verification cannot
itself become the SSRF vector — a `/.well-known` fetch is an outbound request
to a user-supplied host like any other.
"""
from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from app.core.netguard import EndpointRejected, check_endpoint

TXT_PREFIX = "_atlas-prism"
WELL_KNOWN_PATH = "/.well-known/atlas-prism-verification.txt"
TOKEN_PREFIX = "atlas-prism-verification="

# Public resolvers, tried in order. Two, so one being unreachable is not a
# verification failure the user cannot act on.
_DOH = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)

_TIMEOUT = 15
_MAX_BODY = 64 * 1024


class VerificationFailed(Exception):
    """Verification did not succeed. The message is safe to show a user."""


@dataclass(frozen=True)
class Instructions:
    host: str
    token: str
    dns_name: str
    dns_value: str
    file_url: str
    file_contents: str


def new_token() -> str:
    return secrets.token_urlsafe(24)


def instructions_for(host: str, token: str) -> Instructions:
    value = f"{TOKEN_PREFIX}{token}"
    return Instructions(
        host=host,
        token=token,
        dns_name=f"{TXT_PREFIX}.{host}",
        dns_value=value,
        file_url=f"https://{host}{WELL_KNOWN_PATH}",
        file_contents=value,
    )


def _doh_txt(name: str) -> list[str]:
    """TXT records for `name`, via DNS-over-HTTPS."""
    last: str | None = None
    for base in _DOH:
        url = f"{base}?{urllib.parse.urlencode({'name': name, 'type': 'TXT'})}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/dns-json",
            "User-Agent": "atlas-prism-verification",
        })
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read(_MAX_BODY))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            last = str(exc)
            continue
        out: list[str] = []
        for answer in data.get("Answer") or []:
            # TXT answers arrive quoted, and long values are split into
            # multiple quoted chunks that must be concatenated.
            raw = str(answer.get("data", ""))
            parts = [p for p in raw.split('"') if p.strip()]
            out.append("".join(parts).strip() if parts else raw.strip('"'))
        return out
    raise VerificationFailed(
        f"Could not query DNS for {name}: {last or 'no resolver reachable'}."
    )


def verify_dns(host: str, token: str) -> str:
    name = f"{TXT_PREFIX}.{host}"
    records = _doh_txt(name)
    if not records:
        raise VerificationFailed(
            f"No TXT record found at {name}. DNS changes can take a few minutes "
            f"to propagate; publish the record and try again."
        )
    expected = f"{TOKEN_PREFIX}{token}"
    for record in records:
        if record.strip() == expected:
            return f"TXT record at {name} matched."
    found = ", ".join(r[:60] for r in records[:3])
    raise VerificationFailed(
        f"A TXT record exists at {name} but none matched the expected value. "
        f"Found: {found}"
    )


def verify_file(host: str, token: str) -> str:
    url = f"https://{host}{WELL_KNOWN_PATH}"
    # Containment first: this is an outbound request to a user-supplied host.
    try:
        check_endpoint(url)
    except EndpointRejected as exc:
        raise VerificationFailed(str(exc))

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        # A redirect could send the fetch somewhere the containment check never
        # saw, which would make verification itself an SSRF vector.
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-prism-verification"})
    try:
        with opener.open(req, timeout=_TIMEOUT) as resp:
            body = resp.read(_MAX_BODY).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise VerificationFailed(f"{url} returned HTTP {exc.code}.")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise VerificationFailed(f"Could not fetch {url}: {exc}.")

    expected = f"{TOKEN_PREFIX}{token}"
    if expected in body.strip():
        return f"File at {url} matched."
    raise VerificationFailed(
        f"{url} was reachable but did not contain the expected token."
    )


def verify(host: str, token: str, method: str) -> str:
    if method == "dns_txt":
        return verify_dns(host, token)
    if method == "https_file":
        return verify_file(host, token)
    raise VerificationFailed(f"Unknown verification method '{method}'.")
