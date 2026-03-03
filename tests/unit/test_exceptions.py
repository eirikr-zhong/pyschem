"""Unit tests for lib/errors/exceptions.py — Phase 1, errors module.

Test IDs
--------
ERR-01  test_base_exception_instantiable
ERR-02  test_all_exceptions_inherit_base
ERR-03  test_exception_carries_message
ERR-04  test_message_lowercase_no_period
ERR-05  test_exception_context_fields
"""

import pytest

from lib.errors import (
    LayoutConstraintError,
    PinNotFoundError,
    PySchemException,
    RenderLayoutError,
    RenderPathError,
    StyleValidationError,
    SymbolNotFoundError,
)

# All concrete subclasses (6 total, excluding the base)
ALL_SUBCLASSES = [
    StyleValidationError,
    PinNotFoundError,
    SymbolNotFoundError,
    LayoutConstraintError,
    RenderLayoutError,
    RenderPathError,
]


# ---------------------------------------------------------------------------
# ERR-01  Base exception can be instantiated directly
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_base_exception_instantiable():
    """PySchemException must be directly instantiable (not abstract)."""
    err = PySchemException("base error occurred")
    assert isinstance(err, PySchemException)
    assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# ERR-02  All subclasses inherit from PySchemException
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_all_exceptions_inherit_base():
    """Every MVP exception class must be a subclass of PySchemException."""
    for cls in ALL_SUBCLASSES:
        assert issubclass(cls, PySchemException), (
            f"{cls.__name__} does not inherit from PySchemException"
        )


# ---------------------------------------------------------------------------
# ERR-03  Exception carries the message passed at construction
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_exception_carries_message():
    """str(err) must contain the message string supplied at instantiation."""
    msg = "rotation must be one of [0, 90, 180, 270], got 45"
    err = StyleValidationError(msg)
    assert msg in str(err)


# ---------------------------------------------------------------------------
# ERR-04  Convention: messages start lowercase, end without a period
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
class TestMessageConvention:
    """Style convention checks — lowercase start, no trailing period."""

    # Representative sample messages covering every exception class.
    SAMPLE_MESSAGES = [
        (PySchemException,        "base error without period"),
        (StyleValidationError,    "rotation must be one of [0, 90, 180, 270], got 45"),
        (PinNotFoundError,        "pin '3' not found on part R1"),
        (SymbolNotFoundError,     "symbol 'Device:Foo' not found in library"),
        (LayoutConstraintError,   "locked parts P1 and P2 overlap at (10.0, 10.0)"),
        (RenderLayoutError,       "render failed: no coordinates for part R1"),
        (RenderPathError,         "cannot write to path '/read-only/out.dot'"),
    ]

    @pytest.mark.parametrize("cls,msg", SAMPLE_MESSAGES)
    def test_message_lowercase_no_period(self, cls, msg):
        err = cls(msg)
        text = str(err)
        assert text[0].islower(), (
            f"{cls.__name__}: message must start with a lowercase letter, got {text!r}"
        )
        assert not text.endswith("."), (
            f"{cls.__name__}: message must not end with a period, got {text!r}"
        )


# ---------------------------------------------------------------------------
# ERR-05  Exception preserves multiple context fields in str()
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_exception_context_fields():
    """PinNotFoundError('R1', '3') — str must contain both 'R1' and '3'."""
    ref = "R1"
    pin_key = "3"
    err = PinNotFoundError(f"pin '{pin_key}' not found on part {ref}")
    serialised = str(err)
    assert ref in serialised, f"Expected ref {ref!r} in exception message: {serialised!r}"
    assert pin_key in serialised, (
        f"Expected pin key {pin_key!r} in exception message: {serialised!r}"
    )


# ---------------------------------------------------------------------------
# Boundary / edge-case extras (supplements the core ERR-xx IDs)
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_exception_empty_message():
    """Exceptions should accept an empty string without raising."""
    err = PySchemException("")
    assert str(err) == ""


@pytest.mark.unit
@pytest.mark.P1
def test_exception_unicode_message():
    """Exception message may contain Unicode / CJK characters."""
    msg = "引脚 '3' 在 R1 上未找到"
    err = PinNotFoundError(msg)
    assert msg in str(err)


@pytest.mark.unit
@pytest.mark.P1
def test_exception_long_message():
    """Exceptions should handle messages exceeding 1 000 characters."""
    msg = "x" * 1200
    err = LayoutConstraintError(msg)
    assert len(str(err)) >= 1200


@pytest.mark.unit
@pytest.mark.P1
@pytest.mark.parametrize("cls", ALL_SUBCLASSES)
def test_subclass_is_catchable_as_base(cls):
    """Each subclass instance must be caught by an except PySchemException block."""
    raised = cls("test error")
    with pytest.raises(PySchemException):
        raise raised
