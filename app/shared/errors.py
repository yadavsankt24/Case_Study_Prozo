"""
User-facing errors.

Anything raised as `InputError` is shown to the user as-is, so the message must
be plain language and say what to do next. Unexpected exceptions are logged
and replaced with a generic message by the job runner.
"""

from __future__ import annotations


class InputError(Exception):
    """A problem with what the user uploaded (wrong file, corrupt, missing columns ...)."""

    def __init__(self, message: str, *, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field  # which upload slot the problem relates to, if known
