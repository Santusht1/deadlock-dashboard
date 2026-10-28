"""validation.py - Input validation and data containers.

This module only checks and parses data. It never runs any Operating Systems
algorithm, so it has no dependency on algorithms.py.

Conventions
-----------
* Every parser returns (value, errors). When `errors` is non-empty `value`
  is None, so a caller can never accidentally use half-validated data.
* Resource quantities are plain Python ints.
* A "valid but unusual" input (zero Available, zero Need, ...) is NOT an error.
"""
from __future__ import annotations

import math
import numbers
import re
from dataclasses import dataclass
from copy import deepcopy
from typing import Any, List, Optional, Sequence, Tuple

Vector = List[int]
Matrix = List[List[int]]

_INT_RE = re.compile(r"^[+-]?\d+$")


# --------------------------------------------------------------------------
# Data containers
# --------------------------------------------------------------------------
@dataclass
class SystemState:
    """Resource state used by Banker's Algorithm (safety + request handling)."""

    process_ids: List[str]
    resource_ids: List[str]
    allocation: Matrix
    maximum: Matrix
    available: Vector
    total: Optional[Vector] = None  # None when only Available was entered

    @property
    def n_processes(self) -> int:
        return len(self.process_ids)

    @property
    def n_resources(self) -> int:
        return len(self.resource_ids)

    def copy(self) -> "SystemState":
        """Deep copy, so a snapshot can never alias the live state."""
        return deepcopy(self)


@dataclass
class DetectionScenario:
    """Resource state used by the deadlock *detection* model.

    Detection uses an outstanding Request matrix (what each process is
    waiting for right now) instead of Maximum/Need.
    """

    name: str
    description: str
    process_ids: List[str]
    resource_ids: List[str]
    total: Vector
    allocation: Matrix
    request: Matrix
    available: Vector

    def copy(self) -> "DetectionScenario":
        return deepcopy(self)


# --------------------------------------------------------------------------
# Scalar / vector / matrix parsing
# --------------------------------------------------------------------------
def split_tokens(text: str) -> List[str]:
    """Split 'P0, P1 P2' or '1,0,2' into tokens (commas and/or whitespace)."""
    return [t for t in re.split(r"[,\s]+", text.strip()) if t]


def parse_int(value: Any, label: str = "value") -> Tuple[Optional[int], Optional[str]]:
    """Convert one raw value to int. Returns (int, None) or (None, error)."""
    if value is None:
        return None, f"{label} is empty; an integer is required"
    if isinstance(value, bool):
        return None, f"{label} must be an integer, not a boolean"
    if isinstance(value, numbers.Integral):
        return int(value), None
    if isinstance(value, numbers.Real):  # float, numpy.float64, ...
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None, f"{label} is missing or not finite; an integer is required"
        if not number.is_integer():
            return None, f"{label} = {value} is not an integer"
        return int(number), None
    if isinstance(value, str):
        text = value.strip()
        if _INT_RE.match(text):
            return int(text), None
        return None, f"{label} = '{value}' is not an integer"
    return None, f"{label} has unsupported type {type(value).__name__}"


def parse_vector(raw: Any, expected_len: int, label: str,
                 allow_negative: bool = False) -> Tuple[Optional[Vector], List[str]]:
    """Parse a vector from a list or from text such as '1, 0, 2'."""
    errors: List[str] = []
    if isinstance(raw, str):
        items: List[Any] = split_tokens(raw)
    else:
        try:
            items = list(raw)
        except TypeError:
            return None, [f"{label} must be a list of integers"]
    if len(items) != expected_len:
        errors.append(f"{label} must have exactly {expected_len} entries, got {len(items)}")
        return None, errors
    vector: Vector = []
    for j, item in enumerate(items):
        number, error = parse_int(item, f"{label}[{j}]")
        if error:
            errors.append(error)
        elif number < 0 and not allow_negative:
            errors.append(f"{label}[{j}] = {number} is negative; quantities must be >= 0")
        else:
            vector.append(number)
    return (None, errors) if errors else (vector, [])


def parse_matrix(raw: Any, n_rows: int, n_cols: int, label: str) -> Tuple[Optional[Matrix], List[str]]:
    """Parse an n_rows x n_cols matrix of non-negative integers."""
    try:
        rows = [list(r) for r in raw]
    except TypeError:
        return None, [f"{label} must be a matrix (list of rows)"]
    if len(rows) != n_rows:
        return None, [f"{label} must have {n_rows} rows, got {len(rows)}"]
    errors: List[str] = []
    matrix: Matrix = []
    for i, row in enumerate(rows):
        vec, errs = parse_vector(row, n_cols, f"{label}[row {i}]")
        errors += errs
        if vec is not None:
            matrix.append(vec)
    return (None, errors) if errors else (matrix, [])


def validate_identifiers(ids: Sequence[str], kind: str) -> List[str]:
    """Identifiers must be non-empty and unique."""
    errors: List[str] = []
    if len(ids) == 0:
        return [f"At least one {kind} identifier is required"]
    cleaned = [str(x).strip() for x in ids]
    if any(x == "" for x in cleaned):
        errors.append(f"{kind.capitalize()} identifiers must not be empty")
    if len(set(cleaned)) != len(cleaned):
        errors.append(f"{kind.capitalize()} identifiers must be unique: {', '.join(cleaned)}")
    return errors


# --------------------------------------------------------------------------
# Banker's-algorithm state
# --------------------------------------------------------------------------
def build_state(process_ids: Sequence[str], resource_ids: Sequence[str],
                allocation_raw: Any, maximum_raw: Any,
                available_raw: Any = None, total_raw: Any = None
                ) -> Tuple[Optional[SystemState], List[str]]:
    """Validate raw user input and build a SystemState.

    * Total only     -> Available = Total - sum(Allocation)
    * Available only -> accepted, Total unknown
    * Both           -> Available must equal Total - sum(Allocation)
    """
    errors = validate_identifiers(process_ids, "process") + validate_identifiers(resource_ids, "resource")
    if errors:
        return None, errors
    pids = [str(p).strip() for p in process_ids]
    rids = [str(r).strip() for r in resource_ids]
    n, m = len(pids), len(rids)

    allocation, e1 = parse_matrix(allocation_raw, n, m, "Allocation")
    maximum, e2 = parse_matrix(maximum_raw, n, m, "Maximum")
    errors += e1 + e2
    available = total = None
    if available_raw is None and total_raw is None:
        errors.append("Provide Available and/or Total resource counts")
    if available_raw is not None:
        available, e3 = parse_vector(available_raw, m, "Available")
        errors += e3
    if total_raw is not None:
        total, e4 = parse_vector(total_raw, m, "Total")
        errors += e4
    if errors:
        return None, errors

    # Semantic checks (only possible once everything parsed)
    for i in range(n):
        for j in range(m):
            if allocation[i][j] > maximum[i][j]:
                errors.append(f"Allocation exceeds Maximum for process {pids[i]}, resource {rids[j]}: "
                              f"{allocation[i][j]} > {maximum[i][j]}")
    allocated = [sum(allocation[i][j] for i in range(n)) for j in range(m)]
    if total is not None:
        for j in range(m):
            if allocated[j] > total[j]:
                errors.append(f"Resource {rids[j]}: allocated {allocated[j]} exceeds Total {total[j]}")
        if not errors:
            computed = [total[j] - allocated[j] for j in range(m)]
            if available is None:
                available = computed
            elif available != computed:
                errors.append(f"Inconsistent Available: Total - sum(Allocation) = {computed} "
                              f"but Available = {available}")
    if errors:
        return None, errors
    return SystemState(pids, rids, allocation, maximum, available, total), []


def validate_state(state: SystemState) -> List[str]:
    """Re-validate an existing SystemState (used by tests and after commits)."""
    _, errors = build_state(state.process_ids, state.resource_ids, state.allocation,
                            state.maximum, state.available, state.total)
    return errors


# --------------------------------------------------------------------------
# Resource requests (steps 1 and 2 of the request algorithm)
# --------------------------------------------------------------------------
def parse_request(process_ids: Sequence[str], process: str, request_raw: Any,
                  n_resources: int) -> Tuple[Optional[int], Optional[Vector], List[str]]:
    """Check the process identifier, then the request vector.

    Returns (process_index, request_vector, errors).
    The Need / Available comparisons are NOT done here (they need the state).
    """
    errors: List[str] = []
    index: Optional[int] = None
    if process in process_ids:
        index = list(process_ids).index(process)
    else:
        errors.append(f"Invalid process identifier '{process}'. Valid identifiers: {', '.join(process_ids)}")
    vector, vec_errors = parse_vector(request_raw, n_resources, "Request")
    errors += vec_errors
    if errors:
        return None, None, errors
    return index, vector, []


# --------------------------------------------------------------------------
# Detection-model scenarios
# --------------------------------------------------------------------------
def build_detection_scenario(name: str, description: str, process_ids: Sequence[str],
                             resource_ids: Sequence[str], total_raw: Any, allocation_raw: Any,
                             request_raw: Any, available_raw: Any
                             ) -> Tuple[Optional[DetectionScenario], List[str]]:
    """Validate a detection scenario: dimensions, integers and Total consistency."""
    errors = validate_identifiers(process_ids, "process") + validate_identifiers(resource_ids, "resource")
    if errors:
        return None, errors
    pids, rids = [str(p).strip() for p in process_ids], [str(r).strip() for r in resource_ids]
    n, m = len(pids), len(rids)
    total, e1 = parse_vector(total_raw, m, "Total")
    allocation, e2 = parse_matrix(allocation_raw, n, m, "Allocation")
    request, e3 = parse_matrix(request_raw, n, m, "Request")
    available, e4 = parse_vector(available_raw, m, "Available")
    errors = e1 + e2 + e3 + e4
    if errors:
        return None, errors
    for j in range(m):
        allocated = sum(allocation[i][j] for i in range(n))
        if allocated + available[j] != total[j]:
            errors.append(f"Resource {rids[j]}: sum(Allocation) {allocated} + Available {available[j]} "
                          f"!= Total {total[j]}")
    if errors:
        return None, errors
    return DetectionScenario(name, description, pids, rids, total, allocation, request, available), []
