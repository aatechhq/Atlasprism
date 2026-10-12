"""Ownership verification: token handling and the checks themselves.

The DNS answer format is the fiddly part — values arrive quoted, and a long
value is split into several quoted chunks that must be rejoined before
comparison.
"""
from __future__ import annotations

import pytest

from app.core import ownership
from app.core.ownership import (
    TOKEN_PREFIX, VerificationFailed, instructions_for, new_token, verify, verify_dns,
)


def test_tokens_are_unguessable_and_unique():
    tokens = {new_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) >= 24 for t in tokens)


def test_instructions_name_both_methods_concretely():
    ins = instructions_for("api.example.com", "TOK123")
    assert ins.dns_name == "_atlas-prism.api.example.com"
    assert ins.dns_value == f"{TOKEN_PREFIX}TOK123"
    assert ins.file_url == "https://api.example.com/.well-known/atlas-prism-verification.txt"
    assert ins.file_contents == ins.dns_value


def test_dns_verification_succeeds_on_an_exact_match(monkeypatch):
    monkeypatch.setattr(ownership, "_doh_txt", lambda name: [f"{TOKEN_PREFIX}TOK123"])
    assert "matched" in verify_dns("api.example.com", "TOK123")


def test_dns_verification_ignores_unrelated_records(monkeypatch):
    monkeypatch.setattr(ownership, "_doh_txt",
                        lambda name: ["v=spf1 include:_spf.google.com ~all",
                                      f"{TOKEN_PREFIX}TOK123"])
    assert "matched" in verify_dns("api.example.com", "TOK123")


def test_dns_verification_fails_on_a_different_token(monkeypatch):
    """A token from another project must not verify this one."""
    monkeypatch.setattr(ownership, "_doh_txt", lambda name: [f"{TOKEN_PREFIX}SOMEONE-ELSE"])
    with pytest.raises(VerificationFailed, match="none matched"):
        verify_dns("api.example.com", "TOK123")


def test_dns_verification_fails_when_no_record_exists(monkeypatch):
    monkeypatch.setattr(ownership, "_doh_txt", lambda name: [])
    with pytest.raises(VerificationFailed, match="No TXT record"):
        verify_dns("api.example.com", "TOK123")


def test_a_substring_does_not_count_as_a_match(monkeypatch):
    """Guard against a prefix match being treated as proof."""
    monkeypatch.setattr(ownership, "_doh_txt", lambda name: [f"{TOKEN_PREFIX}TOK123-extra"])
    with pytest.raises(VerificationFailed):
        verify_dns("api.example.com", "TOK123")


def test_unknown_method_is_rejected():
    with pytest.raises(VerificationFailed, match="Unknown verification method"):
        verify("api.example.com", "TOK123", "carrier_pigeon")


def test_file_verification_refuses_a_private_host():
    """Verification must not itself become the SSRF vector."""
    with pytest.raises(VerificationFailed):
        ownership.verify_file("localhost", "TOK123")
