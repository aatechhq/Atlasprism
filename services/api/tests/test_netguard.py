"""Containment tests for user-supplied endpoints.

These are the tests that matter most in this repository: a miss here is a
server-side request forgery vulnerability in a security product.
"""
from __future__ import annotations

import pytest

from app.core import netguard
from app.core.netguard import EndpointRejected, check_against_allowlist, check_endpoint


# --------------------------------------------------------------- scheme and shape

@pytest.mark.parametrize("url", [
    "",
    "   ",
    "file:///etc/passwd",
    "gopher://example.com/",
    "ftp://example.com/",
    "not a url",
])
def test_rejects_non_http_schemes_and_junk(url):
    with pytest.raises(EndpointRejected):
        check_endpoint(url)


def test_rejects_plain_http_to_a_remote_host():
    with pytest.raises(EndpointRejected, match="clear text"):
        check_endpoint("http://example.com/v1/chat/completions")


def test_rejects_embedded_credentials():
    with pytest.raises(EndpointRejected, match="Credentials"):
        check_endpoint("https://user:secret@example.com/")


def test_rejects_a_fragment():
    with pytest.raises(EndpointRejected, match="fragment"):
        check_endpoint("https://example.com/v1#frag")


def test_rejects_a_non_standard_port():
    with pytest.raises(EndpointRejected, match="Port"):
        check_endpoint("https://example.com:8080/v1")


# --------------------------------------------------------------- address space

@pytest.mark.parametrize("addr,label", [
    ("127.0.0.1", "loopback — would reach Prism itself"),
    ("10.1.2.3", "private"),
    ("172.16.5.4", "private"),
    ("192.168.1.1", "private"),
    ("169.254.169.254", "cloud instance metadata"),
    ("100.64.0.1", "carrier-grade NAT"),
    ("0.0.0.0", "this host"),
    ("224.0.0.1", "multicast"),
    ("::1", "IPv6 loopback"),
    ("fd00::1", "IPv6 unique local"),
    ("fe80::1", "IPv6 link-local"),
    ("::ffff:10.0.0.1", "IPv4-mapped private address"),
])
def test_rejects_private_and_reserved_space(monkeypatch, addr, label):
    monkeypatch.setattr(netguard, "resolve", lambda host: [addr])
    with pytest.raises(EndpointRejected) as exc:
        check_endpoint("https://evil.example.com/v1")
    assert "private" in str(exc.value) or "reserved" in str(exc.value), label


def test_rejects_when_only_one_of_several_addresses_is_private(monkeypatch):
    """A naive check that looked at the first record would let this through."""
    monkeypatch.setattr(netguard, "resolve", lambda host: ["93.184.216.34", "10.0.0.5"])
    with pytest.raises(EndpointRejected, match="10.0.0.5"):
        check_endpoint("https://split-horizon.example.com/v1")


def test_accepts_a_public_address(monkeypatch):
    monkeypatch.setattr(netguard, "resolve", lambda host: ["93.184.216.34"])
    checked = check_endpoint("https://example.com/v1/chat/completions")
    assert checked.host == "example.com"
    assert checked.addresses == ("93.184.216.34",)


def test_unresolvable_host_is_rejected_not_passed_through(monkeypatch):
    def boom(host):
        raise EndpointRejected("Host 'nope.invalid' could not be resolved: not known.")
    monkeypatch.setattr(netguard, "resolve", boom)
    with pytest.raises(EndpointRejected, match="resolved"):
        check_endpoint("https://nope.invalid/v1")


# --------------------------------------------------------------- localhost opt-in

def test_plain_http_localhost_refused_by_default():
    """Rejected by the scheme rule, which fires before the localhost rule."""
    with pytest.raises(EndpointRejected, match="http"):
        check_endpoint("http://localhost:8000/v1")


def test_https_localhost_refused_by_default():
    """The localhost rule itself: not a reachable target for a deployment."""
    with pytest.raises(EndpointRejected, match="localhost"):
        check_endpoint("https://localhost/v1")


def test_localhost_allowed_only_with_the_explicit_development_flag():
    checked = check_endpoint("http://localhost:8000/v1", allow_insecure_localhost=True)
    assert checked.host == "localhost"


# --------------------------------------------------------------- allowlist

def test_allowlist_and_containment_are_both_required(monkeypatch):
    monkeypatch.setattr(netguard, "resolve", lambda host: ["93.184.216.34"])
    # Passes containment, absent from the allowlist.
    with pytest.raises(EndpointRejected, match="allowlist"):
        check_against_allowlist("https://example.com/v1", {"api.mycompany.com"})
    # In the allowlist and public: accepted.
    ok = check_against_allowlist("https://example.com/v1", {"example.com"})
    assert ok.host == "example.com"


def test_allowlist_does_not_override_containment(monkeypatch):
    """Naming a private host in the allowlist must not make it reachable."""
    monkeypatch.setattr(netguard, "resolve", lambda host: ["169.254.169.254"])
    with pytest.raises(EndpointRejected):
        check_against_allowlist("https://metadata.internal/v1", {"metadata.internal"})


def test_allowlist_match_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(netguard, "resolve", lambda host: ["93.184.216.34"])
    assert check_against_allowlist("https://EXAMPLE.com/v1", {"example.com"}).host == "example.com"
