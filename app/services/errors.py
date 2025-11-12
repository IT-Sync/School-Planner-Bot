from __future__ import annotations


class InputValidationError(Exception):
    """Raised when user input fails validation."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors
