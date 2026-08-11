class TaskSkipped(Exception):
    """Exception raised when a task is skipped due to rate limits or other non-error reasons."""
    pass


class SkipProfile(Exception):
    """Exception raised when a specific profile should be skipped during processing."""
    pass


class AuthenticationError(Exception):
    """Exception raised when authentication fails or session expires."""
    pass


class ReachedFollowLimit(Exception):
    """Exception raised when Instagram's follow / action limit is reached."""
    pass


# Back-compat alias for older imports during the Instagram cutover.
ReachedConnectionLimit = ReachedFollowLimit
