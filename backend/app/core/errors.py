class AppError(Exception):
    """Единый формат ошибки приложения: {code, message, details?}."""

    def __init__(self, code: str, message: str, status: int = 400, details=None, headers=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.details, self.headers = details, headers
