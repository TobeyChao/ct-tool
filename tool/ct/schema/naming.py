from __future__ import annotations


def to_pascal_case(name: str) -> str:
    """Convert ``snake_case`` to ``PascalCase``.

    Single source of truth for the FBS / Accessor type-name convention shared
    across template rendering, FBS generation, and accessor code generation.
    """
    return "".join(part.capitalize() for part in name.split("_"))
