from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


ENGINE = "CAD3D_DETERMINISTIC_RECOGNITION_CONTRACT_V1"

ACCEPTED = "accepted"
REJECTED = "rejected"
ALTERNATE = "alternate"


@dataclass(frozen=True)
class RuleResult:
    """
    Result of ONE deterministic recognition rule.

    A rule has only:
        PASS
        FAIL

    No learned probability is involved.
    """

    rule: str
    passed: bool
    actual: Any = None
    expected: Any = None
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "rule": str(self.rule),
            "passed": bool(self.passed),
            "actual": self.actual,
            "expected": self.expected,
            "reason": str(self.reason or ""),
        }


@dataclass(frozen=True)
class RecognitionDecision:
    """
    Immutable recognition result.

    Detector code may inspect this result but recognition
    contracts NEVER modify CAD geometry or 3ds Max state.
    """

    entity_type: str
    status: str
    classification: str
    reason: str
    rules: tuple
    metadata: Mapping[str, Any]

    @property
    def accepted(self) -> bool:
        return self.status == ACCEPTED

    def as_dict(self) -> dict:
        return {
            "entity_type": str(
                self.entity_type
            ),
            "status": str(
                self.status
            ),
            "accepted": bool(
                self.accepted
            ),
            "classification": str(
                self.classification
            ),
            "reason": str(
                self.reason
            ),
            "rules": [
                rule.as_dict()
                if isinstance(
                    rule,
                    RuleResult,
                )
                else dict(rule)
                for rule in self.rules
            ],
            "metadata": dict(
                self.metadata
            ),
        }


def rule(
    name: str,
    condition: bool,
    *,
    actual: Any = None,
    expected: Any = None,
    reason: str = "",
) -> RuleResult:
    """
    Explicit deterministic rule evaluation.
    """

    return RuleResult(
        rule=str(name),
        passed=bool(condition),
        actual=actual,
        expected=expected,
        reason=str(reason or ""),
    )


def require_all(
    entity_type: str,
    classification: str,
    rules: Iterable[RuleResult],
    *,
    accepted_reason: str,
    rejected_reason: str,
    metadata: Mapping[str, Any] | None = None,
) -> RecognitionDecision:
    """
    ACCEPT only when EVERY supplied rule passes.
    """

    normalized = tuple(rules)

    passed = (
        bool(normalized)
        and all(
            item.passed
            for item in normalized
        )
    )

    return RecognitionDecision(
        entity_type=str(entity_type),
        status=(
            ACCEPTED
            if passed
            else REJECTED
        ),
        classification=str(
            classification
        ),
        reason=(
            str(accepted_reason)
            if passed
            else str(rejected_reason)
        ),
        rules=normalized,
        metadata=dict(
            metadata or {}
        ),
    )


def require_any(
    entity_type: str,
    classification: str,
    rules: Iterable[RuleResult],
    *,
    accepted_reason: str,
    rejected_reason: str,
    metadata: Mapping[str, Any] | None = None,
) -> RecognitionDecision:
    """
    ACCEPT when at least ONE supplied rule passes.
    """

    normalized = tuple(rules)

    passed = any(
        item.passed
        for item in normalized
    )

    return RecognitionDecision(
        entity_type=str(entity_type),
        status=(
            ACCEPTED
            if passed
            else REJECTED
        ),
        classification=str(
            classification
        ),
        reason=(
            str(accepted_reason)
            if passed
            else str(rejected_reason)
        ),
        rules=normalized,
        metadata=dict(
            metadata or {}
        ),
    )


def alternate(
    entity_type: str,
    classification: str,
    *,
    reason: str,
    rules: Iterable[RuleResult] = (),
    metadata: Mapping[str, Any] | None = None,
) -> RecognitionDecision:
    """
    Explicit alternate classification.

    Example:
        window candidate -> rooflight

    This is NOT a failed execution and does not modify geometry.
    """

    return RecognitionDecision(
        entity_type=str(entity_type),
        status=ALTERNATE,
        classification=str(
            classification
        ),
        reason=str(reason),
        rules=tuple(rules),
        metadata=dict(
            metadata or {}
        ),
    )


def failed_rules(
    decision: RecognitionDecision,
) -> tuple:
    return tuple(
        item
        for item in decision.rules
        if not item.passed
    )


def assert_accepted(
    decision: RecognitionDecision,
) -> None:
    """
    Execution layers may call this before performing an action.

    If recognition has not explicitly accepted the object,
    execution MUST stop.
    """

    if not decision.accepted:
        failures = ", ".join(
            item.rule
            for item in failed_rules(
                decision
            )
        )

        raise RuntimeError(
            "Recognition contract rejected execution"
            + (
                ": " + failures
                if failures
                else ""
            )
        )


def self_test() -> None:
    good = require_all(
        "window",
        "facade_window",
        [
            rule(
                "has_geometry",
                True,
            ),
            rule(
                "wall_left",
                True,
            ),
            rule(
                "wall_right",
                True,
            ),
        ],
        accepted_reason=(
            "all-required-rules-passed"
        ),
        rejected_reason=(
            "required-rule-failed"
        ),
    )

    assert good.accepted is True
    assert good.status == ACCEPTED

    bad = require_all(
        "door",
        "door",
        [
            rule(
                "has_arc",
                True,
            ),
            rule(
                "has_jamb_a",
                False,
            ),
        ],
        accepted_reason="door-valid",
        rejected_reason="door-invalid",
    )

    assert bad.accepted is False
    assert bad.status == REJECTED

    rooflight = alternate(
        "window",
        "rooflight",
        reason=(
            "not-supported-by-wall"
        ),
    )

    assert (
        rooflight.status
        == ALTERNATE
    )

    try:
        assert_accepted(
            bad
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Rejected decision reached execution."
        )

    print(
        "DETERMINISTIC RECOGNITION CONTRACT "
        "V1 SELF-TEST: OK"
    )


if __name__ == "__main__":
    self_test()
