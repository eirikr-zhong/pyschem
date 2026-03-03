"""Unit tests for lib/core/style.py — Phase 1, style module.

Test IDs
--------
STY-01  test_style_valid_defaults
STY-02  test_rotation_invalid_raises
STY-03  test_anchor_invalid_raises
STY-04  test_locked_wrong_type_raises
STY-05  test_negative_coordinates_allowed
STY-06  test_float_coordinates_allowed
STY-07  test_rotation_all_valid_values
STY-08  test_anchor_all_valid_values
"""

import pytest

from lib.core.style import VALID_ANCHORS, VALID_ROTATIONS, DefaultPlacementStyle, Style
from lib.errors import StyleValidationError


# ---------------------------------------------------------------------------
# STY-01  Default values conform to spec
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_style_valid_defaults():
    """Style() with no args must produce the documented default values."""
    s = Style()
    assert s.x is None
    assert s.y is None
    assert s.anchor == "center"
    assert s.rotation == 0
    assert s.locked is False
    assert s.z_index == 0


# ---------------------------------------------------------------------------
# STY-02  Invalid rotation raises StyleValidationError
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_rotation_invalid_raises():
    """rotation=45 (not in {0,90,180,270}) must raise StyleValidationError."""
    with pytest.raises(StyleValidationError) as exc_info:
        Style(rotation=45)
    assert "rotation" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# STY-03  Invalid anchor raises StyleValidationError
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_anchor_invalid_raises():
    """anchor='middle' (not in valid set) must raise StyleValidationError."""
    with pytest.raises(StyleValidationError) as exc_info:
        Style(anchor="middle")
    assert "anchor" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# STY-04  Wrong type for locked raises StyleValidationError
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P0
def test_locked_wrong_type_raises():
    """locked='true' (string instead of bool) must raise StyleValidationError."""
    with pytest.raises(StyleValidationError):
        Style(locked="true")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# STY-05  Negative coordinates are allowed
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_negative_coordinates_allowed():
    """x=-10, y=-20 must create a Style without raising."""
    s = Style(x=-10, y=-20)
    assert s.x == pytest.approx(-10)
    assert s.y == pytest.approx(-20)


# ---------------------------------------------------------------------------
# STY-06  Float coordinates are allowed
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_float_coordinates_allowed():
    """x=1.5, y=3.14 must create a Style without raising."""
    s = Style(x=1.5, y=3.14)
    assert s.x == pytest.approx(1.5)
    assert s.y == pytest.approx(3.14)


# ---------------------------------------------------------------------------
# STY-07  All four valid rotation values are accepted
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
@pytest.mark.parametrize("deg", sorted(VALID_ROTATIONS))
def test_rotation_all_valid_values(deg):
    """rotation ∈ {0, 90, 180, 270} must all pass validation."""
    s = Style(rotation=deg)
    assert s.rotation == deg


# ---------------------------------------------------------------------------
# STY-08  All five valid anchor values are accepted
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
@pytest.mark.parametrize("anchor", sorted(VALID_ANCHORS))
def test_anchor_all_valid_values(anchor):
    """anchor ∈ {center, left, right, top, bottom} must all pass validation."""
    s = Style(anchor=anchor)
    assert s.anchor == anchor


# ---------------------------------------------------------------------------
# Boundary extras — invalid rotation values
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
@pytest.mark.parametrize("bad_rotation", [-1, 1, 45, 360, None])
def test_rotation_boundary_invalids(bad_rotation):
    """Rotation values outside {0,90,180,270} must raise StyleValidationError."""
    with pytest.raises(StyleValidationError):
        Style(rotation=bad_rotation)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Boundary extras — invalid anchor values
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
@pytest.mark.parametrize("bad_anchor", ["CENTER", "MIDDLE", "", None])
def test_anchor_boundary_invalids(bad_anchor):
    """Anchor values not in the valid set must raise StyleValidationError."""
    with pytest.raises(StyleValidationError):
        Style(anchor=bad_anchor)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Boundary extras — wrong type for z_index
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_z_index_wrong_type_raises():
    """z_index='0' (string) must raise StyleValidationError."""
    with pytest.raises(StyleValidationError):
        Style(z_index="0")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Boundary extras — wrong type for coordinates
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
@pytest.mark.parametrize("axis,kwargs", [
    ("x", {"x": "10"}),
    ("y", {"y": "10"}),
])
def test_coordinate_wrong_type_raises(axis, kwargs):
    """String coordinates must raise StyleValidationError."""
    with pytest.raises(StyleValidationError):
        Style(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DefaultPlacementStyle helper
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.P1
def test_default_placement_style_returns_style():
    """DefaultPlacementStyle() must return a Style with spec-compliant defaults."""
    s = DefaultPlacementStyle()
    assert isinstance(s, Style)
    assert s.x is None
    assert s.y is None
    assert s.anchor == "center"
    assert s.rotation == 0
    assert s.locked is False
    assert s.z_index == 0


@pytest.mark.unit
@pytest.mark.P1
def test_default_placement_style_returns_new_instance():
    """Each call to DefaultPlacementStyle() must return a distinct object."""
    s1 = DefaultPlacementStyle()
    s2 = DefaultPlacementStyle()
    assert s1 is not s2
