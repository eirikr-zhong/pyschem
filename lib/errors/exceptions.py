"""Exception classes for pyschem library."""


class PySchemException(Exception):
    """Base exception for all pyschem errors."""
    pass


class StyleValidationError(PySchemException):
    pass


class PinNotFoundError(PySchemException):
    pass


class SymbolNotFoundError(PySchemException):
    pass


class FootprintNotFoundError(PySchemException):
    pass


class LayoutConstraintError(PySchemException):
    pass


class RenderLayoutError(PySchemException):
    pass


class RenderPathError(PySchemException):
    pass


class ERCError(PySchemException):
    """Raised when an Electrical Rules Check violation is detected."""
    pass
