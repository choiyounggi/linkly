class BusinessRule(Exception):
    """422 problem+json — a business rule rejected the request."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail or code
        super().__init__(self.detail)


class NotFound(Exception):
    """404 problem+json — referenced entity does not exist."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail or code
        super().__init__(self.detail)


class IllegalTransition(Exception):
    """409 problem+json — the requested state transition is not allowed."""

    def __init__(self, code: str = "illegal_transition", detail: str = ""):
        self.code = code
        self.detail = detail or code
        super().__init__(self.detail)


class Forbidden(Exception):
    """403 problem+json — caller lacks the required role."""

    def __init__(self, code: str = "forbidden", detail: str = ""):
        self.code = code
        self.detail = detail or code
        super().__init__(self.detail)


class InjectedFailure(Exception):
    """500 problem+json — test-only fault injected mid-transaction (ORDERHUB_TEST_HOOKS)."""

    def __init__(self, code: str = "injected_failure", detail: str = ""):
        self.code = code
        self.detail = detail or code
        super().__init__(self.detail)
