class AppError(Exception):
    """Base application exception."""


class NotFoundError(AppError):
    pass


class ConflictError(AppError):
    pass


class DownloadError(AppError):
    pass


class PrinterError(AppError):
    pass

