"""Safe local errors for invalid or incomplete v2 decision inputs."""


class DecisionInputError(ValueError):
    """Raised when structured decision input violates a frozen rule."""


class DecisionNotFinalizableError(ValueError):
    """Raised when an approved rule prevents a formal final decision."""
