"""Unified style resolution helpers.

Precedence:
part.style > template.style > Style.default()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib.core.render_style import RenderStyle
from lib.core.style import Style

if TYPE_CHECKING:
    from lib.core.part import Part
    from lib.core.render_style import RenderTemplate


def _coerce_to_style(style: Style | RenderStyle | None) -> Style:
    """Coerce a legacy render style object into unified :class:`Style`."""
    if style is None:
        return Style()
    if isinstance(style, Style):
        return style
    return Style().merge(style)


def resolve_style(
    part: "Part | None" = None,
    template: "RenderTemplate | None" = None,
) -> Style:
    """Resolve the effective style with explicit precedence.

    Resolution order:
    1) :meth:`Style.default`
    2) template style (if provided)
    3) part style (if provided)
    """
    resolved = Style.default()
    if template is not None:
        resolved = resolved.merge(_coerce_to_style(template.style))
    if part is not None:
        resolved = resolved.merge(_coerce_to_style(part.get_style()))
    return resolved
