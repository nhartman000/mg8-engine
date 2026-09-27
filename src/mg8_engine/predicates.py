"""Deterministic predicate evaluation for the MG8 reference profile."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_MISSING = object()
_EXPRESSION = re.compile(
    r"^\s*(?P<path>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"(?:\s*(?P<operator>==|!=|>=|<=|>|<)\s*(?P<value>.+?))?\s*$"
)


@dataclass(frozen=True)
class PredicateResult:
    result: str
    evidence: list[dict[str, Any]]


def _resolve_path(state: dict[str, Any], path: str) -> Any:
    value: Any = state
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _literal(text: str) -> Any:
    token = text.strip()
    lowered = token.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    if (token.startswith('"') and token.endswith('"')) or (
        token.startswith("'") and token.endswith("'")
    ):
        return token[1:-1]
    try:
        return float(token) if any(char in token for char in ".eE") else int(token)
    except ValueError:
        return token


def _compare(actual: Any, operator: str | None, expected: Any) -> bool:
    if operator is None:
        return bool(actual)
    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    try:
        if operator == ">":
            return actual > expected
        if operator == "<":
            return actual < expected
        if operator == ">=":
            return actual >= expected
        if operator == "<=":
            return actual <= expected
    except TypeError:
        return False
    raise ValueError(f"Unsupported predicate operator: {operator}")


def evaluate_conditions(
    conditions: list[Any], state: dict[str, Any], gate_type: str = "AND"
) -> PredicateResult:
    """Evaluate bounded predicates without eval or other code execution."""
    evidence: list[dict[str, Any]] = []
    resolved: list[bool | None] = []
    for condition in conditions:
        if isinstance(condition, str):
            match = _EXPRESSION.fullmatch(condition)
            if not match:
                raise ValueError(f"Unsupported condition expression: {condition!r}")
            path = match.group("path")
            operator = match.group("operator")
            expected = _literal(match.group("value")) if operator else True
        elif isinstance(condition, dict):
            path = condition.get("path")
            operator = condition.get("operator", "==")
            expected = condition.get("value")
            if not isinstance(path, str) or operator not in {"==", "!=", ">", "<", ">=", "<="}:
                raise ValueError(f"Unsupported structured condition: {condition!r}")
        else:
            raise ValueError(f"Condition must be a string or object: {condition!r}")

        actual = _resolve_path(state, path)
        if actual is _MISSING:
            passed = None
            shown_actual: Any = {"missing": True}
        else:
            passed = _compare(actual, operator, expected)
            shown_actual = actual
        resolved.append(passed)
        evidence.append({"condition": condition, "path": path, "actual": shown_actual, "expected": expected, "satisfied": passed})

    mode = gate_type.upper()
    if mode not in {"AND", "CONDITION", "OR"}:
        raise ValueError(f"Unsupported deterministic gate type: {gate_type}")
    if mode == "OR":
        result = "PASS" if True in resolved else "INTERMEDIATE" if None in resolved else "FAIL"
    else:
        result = "FAIL" if False in resolved else "INTERMEDIATE" if None in resolved else "PASS"
    return PredicateResult(result=result, evidence=evidence)
