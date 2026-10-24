class WorkflowError(ValueError):
    """Action not allowed in the current state. Message is safe to show."""


class PermissionDenied(PermissionError):
    """The user's role does not allow this action."""


class NotFound(LookupError):
    pass
