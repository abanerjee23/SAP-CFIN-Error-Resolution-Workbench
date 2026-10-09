"""Provider failures shared by versioned, independently imported workflows."""


class RetryableStageError(RuntimeError):
    """A transient provider failure; every retry still needs a new reservation."""
