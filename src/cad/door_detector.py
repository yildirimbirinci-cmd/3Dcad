from __future__ import annotations

from dataclasses import dataclass

from cad.model import CadDocument
from cad.door_rulebook import (
    grab_local_door_geometry,
    is_arc,
    validate_door_arc,
)


Point2D = tuple[float, float]
Bounds2D = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class InteriorDoorCandidate:
    arc_index: int
    layer: str
    arc_center: Point2D
    arc_radius: float
    grab_bounds: Bounds2D
    grab_center: Point2D
    grab_width: float
    grab_height: float
    display_primitive_indices: tuple[int, ...]


def detect_interior_doors(
    document: CadDocument,
) -> list[InteriorDoorCandidate]:
    result: list[InteriorDoorCandidate] = []

    for arc_index, primitive in enumerate(document.primitives):
        if not is_arc(primitive):
            continue

        validated = validate_door_arc(
            document,
            arc_index,
        )

        if validated is None:
            continue

        grabbed = grab_local_door_geometry(
            document,
            validated,
        )

        result.append(
            InteriorDoorCandidate(
                arc_index=arc_index,
                layer=validated["layer"],
                arc_center=grabbed["arc_center"],
                arc_radius=float(grabbed["arc_radius"]),
                grab_bounds=grabbed["bounds"],
                grab_center=grabbed["center"],
                grab_width=float(grabbed["width"]),
                grab_height=float(grabbed["height"]),
                display_primitive_indices=grabbed["primitive_indices"],
            )
        )

    return result
