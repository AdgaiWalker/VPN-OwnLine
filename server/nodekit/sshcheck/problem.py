"""Structured, secret-free error used by the SSH preflight worker."""


class Problem(Exception):
    def __init__(self, code, message, status=400, detail=None):
        self.code, self.message, self.status, self.detail = code, message, status, detail
        super().__init__(message)
