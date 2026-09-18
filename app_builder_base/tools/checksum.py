# Copyright 2026 Avunu LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Content hashing used for drift detection."""

from __future__ import annotations

import hashlib
import os
from typing import Literal


def hash_text(text: str | bytes) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def hash_file(path: str) -> str | Literal[False]:
    """Hash a file's contents, or return ``False`` when it is absent.

    A missing file is a meaningful state (the developer deleted generated
    output), not an error, so callers can distinguish it from a mismatch.
    """
    if not os.path.isfile(path):
        return False
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()
