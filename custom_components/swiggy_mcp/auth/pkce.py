"""PKCE helpers — RFC 7636, S256 method."""
from __future__ import annotations

import base64
import hashlib
import os
import re


def generate_code_verifier() -> str:
    """Generate a cryptographically random PKCE code verifier (43-128 chars, unreserved chars only)."""
    raw = base64.urlsafe_b64encode(os.urandom(32)).decode()
    # Strip padding characters; keep only unreserved chars as per RFC 7636 §4.1
    verifier = re.sub(r"[^a-zA-Z0-9._~-]", "", raw)
    return verifier[:128]


def generate_code_challenge(verifier: str) -> str:
    """Derive S256 code challenge from a verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
