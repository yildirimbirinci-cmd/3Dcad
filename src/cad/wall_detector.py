from __future__ import annotations

from dataclasses import dataclass

from cad.model import CadDocument
from cad.wall_rulebook import (
    door_primitive_indices,
    primitive_layer,
    window_primitive_indices,
)


@dataclass(frozen=True, slots=True)
class WallCandidate:
    primitive_index: int
    layer: str


def available_wall_primitive_indices(
    document: CadDocument,
    door_candidates=None,
    window_candidates=None,
):
    """
    Duvar kurallari icin kullanilabilecek temel CAD havuzu.

    TUM CAD PRIMITIVELERI
    - KAPI PRIMITIVELERI
    - PENCERE PRIMITIVELERI
    = DUVAR ADAY HAVUZU

    Burada herhangi bir duvar secim kurali uygulanmaz.
    """

    door_indices = set(
        door_primitive_indices(door_candidates)
    )

    window_indices = set(
        window_primitive_indices(window_candidates)
    )

    claimed_indices = door_indices | window_indices

    return tuple(
        index
        for index in range(len(document.primitives))
        if index not in claimed_indices
    )


def detect_walls(
    document: CadDocument,
    door_candidates=None,
    window_candidates=None,
    *args,
    **kwargs,
):
    """
    WALL RULES RESET.

    Kapi ve pencere secimleri korunur.

    Yeni duvar kurallari tanimlanana kadar
    hicbir CAD primitive'i duvar olarak secilmez.
    """

    available_wall_primitive_indices(
        document,
        door_candidates,
        window_candidates,
    )

    return []