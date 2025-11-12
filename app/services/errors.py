from __future__ import annotations


class InputValidationError(Exception):
    """Raised when user input fails validation."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


class ShareLinkNotFoundError(Exception):
    """Raised when provided share token is invalid."""


class ShareImportError(Exception):
    """Raised when share import cannot be performed."""
