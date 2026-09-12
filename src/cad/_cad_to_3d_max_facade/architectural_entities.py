from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


ENGINE = "CAD3D_ARCHITECTURAL_ENTITY_V1"

ENTITY_WALL = "wall"
ENTITY_DOOR = "door"
ENTITY_WINDOW = "window"
ENTITY_OPENING = "opening"
ENTITY_LEVEL = "level"

KNOWN_ENTITY_TYPES = frozenset(
    {
        ENTITY_WALL,
        ENTITY_DOOR,
        ENTITY_WINDOW,
        ENTITY_OPENING,
        ENTITY_LEVEL,
    }
)


@dataclass
class ArchitecturalEntity:
    """
    Common architectural entity container.

    IMPORTANT:
    This class does NOT detect geometry.
    This class does NOT modify CAD geometry.
    This class does NOT modify 3ds Max.

    It only provides a deterministic common data contract
    between recognition and execution layers.
    """

    entity_type: str

    entity_id: str = ""

    geometry: Mapping[str, Any] = field(
        default_factory=dict
    )

    structural_relation: Mapping[str, Any] = field(
        default_factory=dict
    )

    recognition_contract: Mapping[str, Any] = field(
        default_factory=dict
    )

    source_geometry: Any = None

    source_layer: str = ""

    execution_permissions: Mapping[str, bool] = field(
        default_factory=dict
    )

    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        self.entity_type = str(
            self.entity_type or ""
        ).strip().lower()

        self.entity_id = str(
            self.entity_id or ""
        ).strip()

        self.source_layer = str(
            self.source_layer or ""
        ).strip()

        self.geometry = dict(
            self.geometry or {}
        )

        self.structural_relation = dict(
            self.structural_relation or {}
        )

        self.recognition_contract = dict(
            self.recognition_contract or {}
        )

        self.execution_permissions = {
            str(key): bool(value)
            for key, value in dict(
                self.execution_permissions or {}
            ).items()
        }

        self.metadata = dict(
            self.metadata or {}
        )

    @property
    def recognized(self) -> bool:
        """
        True only when recognition contract explicitly says
        the entity was accepted.
        """

        return bool(
            self.recognition_contract.get(
                "accepted",
                False,
            )
        )

    def can_execute(
        self,
        operation: str,
    ) -> bool:
        """
        Query explicit execution permission.

        Missing permission always means False.
        """

        key = str(
            operation or ""
        ).strip()

        if not key:
            return False

        return bool(
            self.execution_permissions.get(
                key,
                False,
            )
        )

    def require_execution(
        self,
        operation: str,
    ) -> None:
        """
        Hard execution guard.

        Execution cannot proceed unless permission exists
        explicitly and is True.
        """

        key = str(
            operation or ""
        ).strip()

        if not self.recognized:
            raise RuntimeError(
                "Architectural entity is not recognized."
            )

        if not self.can_execute(
            key
        ):
            raise RuntimeError(
                "Execution permission denied: "
                + key
            )

    def as_dict(self) -> dict:
        return {
            "engine": ENGINE,

            "entity_type":
                self.entity_type,

            "entity_id":
                self.entity_id,

            "geometry":
                dict(
                    self.geometry
                ),

            "structural_relation":
                dict(
                    self.structural_relation
                ),

            "recognition_contract":
                dict(
                    self.recognition_contract
                ),

            "source_geometry":
                self.source_geometry,

            "source_layer":
                self.source_layer,

            "execution_permissions":
                dict(
                    self.execution_permissions
                ),

            "metadata":
                dict(
                    self.metadata
                ),
        }


def create_entity(
    entity_type: str,
    *,
    entity_id: str = "",
    geometry: Mapping[str, Any] | None = None,
    structural_relation: Mapping[str, Any] | None = None,
    recognition_contract: Mapping[str, Any] | None = None,
    source_geometry: Any = None,
    source_layer: str = "",
    execution_permissions: Mapping[str, bool] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ArchitecturalEntity:
    """
    Explicit constructor used by future detector adapters.
    """

    return ArchitecturalEntity(
        entity_type=entity_type,
        entity_id=entity_id,
        geometry=dict(
            geometry or {}
        ),
        structural_relation=dict(
            structural_relation or {}
        ),
        recognition_contract=dict(
            recognition_contract or {}
        ),
        source_geometry=source_geometry,
        source_layer=source_layer,
        execution_permissions=dict(
            execution_permissions or {}
        ),
        metadata=dict(
            metadata or {}
        ),
    )


def self_test() -> None:
    door = create_entity(
        ENTITY_DOOR,
        entity_id="D001",
        geometry={
            "jamb_a": (0.0, 0.0),
            "jamb_b": (900.0, 0.0),
            "width": 900.0,
        },
        structural_relation={
            "jambs_resolved": True,
        },
        recognition_contract={
            "accepted": True,
            "classification": "door",
        },
        source_layer="A-DOOR",
        execution_permissions={
            "bridge": True,
            "delete": False,
        },
    )

    assert door.entity_type == ENTITY_DOOR
    assert door.recognized is True
    assert door.can_execute("bridge") is True
    assert door.can_execute("delete") is False
    assert door.can_execute("unknown") is False

    door.require_execution(
        "bridge"
    )

    try:
        door.require_execution(
            "delete"
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Denied operation reached execution."
        )

    rejected = create_entity(
        ENTITY_WINDOW,
        recognition_contract={
            "accepted": False,
        },
        execution_permissions={
            "cut_opening": True,
        },
    )

    try:
        rejected.require_execution(
            "cut_opening"
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Unrecognized entity reached execution."
        )

    print(
        "ARCHITECTURAL ENTITY V1 SELF-TEST: OK"
    )


if __name__ == "__main__":
    self_test()
