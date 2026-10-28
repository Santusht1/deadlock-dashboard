"""test_algorithms.py - Automated pytest tests for algorithms.py and validation.py.

Run with:  python -m pytest -v
These are UNIT tests. The dashboard's "Test Cases and Results" page shows separate
ANALYTICAL results (TC1-TC6); both call the same algorithm functions.
"""
import pytest

import algorithms as alg
from validation import build_detection_scenario, build_state, parse_request, validate_state


@pytest.fixture
def base():
    return alg.example_safe_state()


# ---------------- Need matrix and safety algorithm ----------------
def test_need_calculation(base):
    need = alg.calculate_need(base.maximum, base.allocation)
    assert need == [[7, 4, 3], [1, 2, 2], [6, 0, 0], [0, 1, 1], [4, 3, 1]]


def test_default_example_is_valid(base):
    assert validate_state(base) == []
    assert base.total == [10, 5, 7]


def test_safe_sequence_for_example(base):
    result = alg.check_safety(base)
    assert result.is_safe and result.status == alg.SAFE_STATE
    assert sorted(result.safe_sequence) == sorted(base.process_ids)
    assert result.unfinished == []


def test_safe_sequence_each_step_is_really_runnable(base):
    """Each selected process must satisfy Need <= Work at ITS step; Work grows correctly."""
    result = alg.check_safety(base)
    work = list(base.available)
    assert result.initial_work == work
    for step in result.steps:
        i = base.process_ids.index(step.process)
        need_i = [m - a for m, a in zip(base.maximum[i], base.allocation[i])]
        assert step.work_before == work
        assert all(n <= w for n, w in zip(need_i, work))
        work = [w + a for w, a in zip(work, base.allocation[i])]
        assert step.work_after == work
    assert work == base.total            # all resources returned at the end
    ok, _ = alg.verify_safe_sequence(base, result.safe_sequence)
    assert ok


def test_verify_safe_sequence_rejects_bad_order(base):
    ok, msg = alg.verify_safe_sequence(base, ["P0", "P1", "P2", "P3", "P4"])
    assert not ok and "P0 cannot finish" in msg


def test_unsafe_state_identified():
    state, _ = build_state(["P0", "P1"], ["A", "B"], [[1, 0], [0, 1]], [[3, 3], [3, 3]], [1, 1])
    result = alg.check_safety(state)
    assert not result.is_safe and result.status == alg.UNSAFE_STATE
    assert result.safe_sequence == [] and result.unfinished == ["P0", "P1"]


def test_unsafe_is_not_reported_as_deadlock():
    """An unsafe state is a separate concept: the detector finds no deadlock here
    because every process currently asks for nothing."""
    state, _ = build_state(["P0", "P1"], ["A", "B"], [[1, 0], [0, 1]], [[3, 3], [3, 3]], [1, 1])
    assert not alg.check_safety(state).is_safe
    scenario, errs = build_detection_scenario("x", "", state.process_ids, state.resource_ids, [2, 2],
                                              state.allocation, [[0, 0], [0, 0]], state.available)
    assert errs == [] and not alg.detect_deadlock(scenario).deadlock_detected


# ---------------- Resource requests ----------------
def test_request_exceeding_need_is_rejected(base):
    r = alg.handle_request(base, "P1", [2, 0, 0])      # Need of P1 is [1, 2, 2]
    assert r.status == alg.INVALID_INPUT and r.invalid and not r.must_wait and not r.granted
    assert "exceeds the remaining Need" in r.reason
    assert r.state_unchanged


def test_request_exceeding_available_waits_and_does_not_modify_state(base):
    before = base.copy()
    proc, req = alg.SCENARIO_B_REQUEST
    r = alg.handle_request(base, proc, req)
    assert r.status == alg.REQUEST_EXCEEDS_AVAILABLE
    assert r.must_wait and not r.invalid and not r.granted
    assert r.final_state.allocation == before.allocation
    assert r.final_state.available == before.available
    assert base == before                               # input object untouched
    assert r.available_before == [3, 3, 2]


def test_unsafe_request_denied_and_state_restored(base):
    before = base.copy()
    proc, req = alg.SCENARIO_C_REQUEST
    assert alg.check_safety(base).is_safe               # precondition: initial state safe
    need = alg.calculate_need(base.maximum, base.allocation)[base.process_ids.index(proc)]
    assert alg.vec_leq(req, need) and alg.vec_leq(req, base.available)
    r = alg.handle_request(base, proc, req)
    assert r.status == alg.REQUEST_DENIED_UNSAFE and not r.granted
    assert r.safety is not None and not r.safety.is_safe
    # tentative state really had the allocation applied ...
    assert r.tentative.allocation[4] == [3, 3, 2] and r.tentative.available == [0, 0, 2]
    # ... but the final state is the exact original
    assert r.final_state == before and r.state_unchanged and base == before


def test_unsafe_request_is_found_by_exhaustive_search(base):
    assert alg.SCENARIO_C_REQUEST in alg.find_unsafe_requests(base, max_results=1000)


def test_safe_request_is_committed(base):
    r = alg.handle_request(base, "P1", [1, 0, 2])
    assert r.status == alg.REQUEST_GRANTED and r.granted
    assert r.final_state.allocation[1] == [3, 0, 2]
    assert r.final_state.available == [2, 3, 0]
    assert base.allocation[1] == [2, 0, 0]              # original object not mutated


def test_zero_available_and_request_waits():
    state, _ = build_state(["P0"], ["A"], [[1]], [[3]], [0])
    r = alg.handle_request(state, "P0", [1])
    assert r.status == alg.REQUEST_EXCEEDS_AVAILABLE and r.must_wait and not r.invalid


# ---------------- Detection (separate from Banker's) ----------------
def test_genuine_deadlock_detected():
    scn = alg.deadlock_examples()["Classic two-process deadlock"]
    result = alg.detect_deadlock(scn)
    assert result.status == alg.DEADLOCK_DETECTED
    assert result.deadlocked == ["P0", "P1"] and result.steps == []
    assert result.wait_cycle is not None


def test_bystander_with_zero_allocation_is_not_deadlocked():
    scn = alg.deadlock_examples()["Deadlock with a bystander process"]
    result = alg.detect_deadlock(scn)
    assert result.initial_finish == [False, False, True]
    assert result.deadlocked == ["P0", "P1"]


def test_circular_wait_without_deadlock():
    scn = alg.deadlock_examples()["Circular wait but NO deadlock (multi-instance)"]
    result = alg.detect_deadlock(scn)
    assert result.wait_cycle is not None                # a cycle exists ...
    assert not result.deadlock_detected                 # ... but everyone can finish
    assert [s.process for s in result.steps] == ["P2", "P1", "P0"]


def test_detection_examples_are_internally_consistent():
    for name, s in alg.deadlock_examples().items():
        _, errors = build_detection_scenario(s.name, s.description, s.process_ids, s.resource_ids,
                                             s.total, s.allocation, s.request, s.available)
        assert errors == [], name


def test_detection_does_not_use_banker_safety(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("detector must not call check_safety")
    monkeypatch.setattr(alg, "check_safety", boom)
    assert alg.detect_deadlock(alg.deadlock_examples()["Classic two-process deadlock"]).deadlock_detected


# ---------------- Recovery ----------------
def test_recovery_releases_resources_and_clears_deadlock():
    scn = alg.deadlock_examples()["Classic two-process deadlock"]
    rec = alg.terminate_process(scn, "P0")
    assert rec.released == [1, 0]
    assert rec.after.allocation[0] == [0, 0] and rec.after.request[0] == [0, 0]
    assert rec.after.available == [1, 0]
    assert rec.consistent
    assert rec.detection_before.deadlock_detected
    assert not rec.detection_after.deadlock_detected
    assert scn.allocation[0] == [1, 0]                  # original scenario untouched


def test_recovery_unknown_process_raises():
    with pytest.raises(ValueError):
        alg.terminate_process(alg.deadlock_examples()["Classic two-process deadlock"], "P9")


def test_suggest_victim_picks_cheapest_deadlocked_process():
    scn = alg.deadlock_examples()["Deadlock with a bystander process"]
    assert alg.suggest_victim(scn) in ("P0", "P1")
    assert alg.suggest_victim(alg.deadlock_examples()["Circular wait but NO deadlock (multi-instance)"]) is None


# ---------------- Prevention ----------------
def test_ordering_rejects_violating_request():
    check = alg.check_resource_ordering(held=[0, 1], request=[1, 0], resource_ids=["A", "B"])
    assert not check.allowed and "increasing rank" in check.messages[0]


def test_ordering_allows_increasing_requests():
    assert alg.check_resource_ordering([1, 0], [0, 1], ["A", "B"]).allowed
    assert alg.check_resource_ordering([0, 0], [1, 1], ["A", "B"]).allowed


def test_hold_and_wait_policy():
    assert not alg.check_hold_and_wait([1, 0], [0, 1], [1, 1]).allowed
    assert alg.check_hold_and_wait([0, 0], [1, 1], [1, 1]).allowed


def test_prevention_simulation_deadlocks_without_policy_and_not_with_ordering():
    p, r, t = alg.PREVENTION_PROCESSES, alg.PREVENTION_RESOURCES, alg.PREVENTION_TOTAL
    base = alg.simulate_acquisition(p, r, t, alg.prevention_plans("unordered"))
    assert base.deadlocked == ["P0", "P1"]
    ordered = alg.simulate_acquisition(p, r, t, alg.prevention_plans("ordered"), alg.ordering_enforcer(r))
    assert ordered.deadlocked == [] and sorted(ordered.completed) == p
    violating = alg.simulate_acquisition(p, r, t, alg.prevention_plans("unordered"), alg.ordering_enforcer(r))
    assert violating.rejected == ["P1"] and violating.deadlocked == []


def test_hold_and_wait_simulation():
    p, r, t = alg.PREVENTION_PROCESSES, alg.PREVENTION_RESOURCES, alg.PREVENTION_TOTAL
    plans = alg.prevention_plans("all_at_once")
    result = alg.simulate_acquisition(p, r, t, plans, alg.hold_wait_enforcer(plans))
    assert result.deadlocked == [] and sorted(result.completed) == p


# ---------------- Boundary and invalid input ----------------
def test_zero_need_process_can_finish_first():
    state, errs = build_state(["P0", "P1"], ["A"], [[2], [0]], [[2], [3]], [1])
    assert errs == []
    result = alg.check_safety(state)
    assert result.safe_sequence[0] == "P0" and result.is_safe


def test_zero_available_is_valid_and_handled():
    state, errs = build_state(["P0", "P1"], ["A", "B"], [[1, 1], [0, 0]], [[1, 1], [1, 1]], [0, 0], [1, 1])
    assert errs == [] and state.available == [0, 0]
    result = alg.check_safety(state)
    assert result.is_safe and result.safe_sequence == ["P0", "P1"]


def test_no_process_can_proceed_is_valid_but_unsafe():
    state, errs = build_state(["P0", "P1"], ["A", "B"], [[1, 0], [0, 1]], [[3, 3], [3, 3]], [1, 1])
    assert errs == []
    result = alg.check_safety(state)
    assert not result.is_safe and result.steps == []


def test_all_processes_completed():
    state, errs = build_state(["P0", "P1"], ["A"], [[0], [0]], [[0], [0]], None, [4])
    assert errs == [] and state.available == [4]
    assert alg.check_safety(state).is_safe


def test_negative_requests_rejected(base):
    r = alg.handle_request(base, "P1", [-1, 0, 0])
    assert r.status == alg.INVALID_INPUT and r.invalid and r.state_unchanged
    assert any("negative" in e for e in r.errors)


def test_wrong_length_request_rejected(base):
    for bad in ([1, 0], [1, 0, 0, 0], ""):
        r = alg.handle_request(base, "P1", bad)
        assert r.status == alg.INVALID_INPUT and r.state_unchanged


def test_non_integer_request_rejected(base):
    for bad in ([1.5, 0, 0], ["a", 0, 0], "1, x, 0"):
        assert alg.handle_request(base, "P1", bad).status == alg.INVALID_INPUT


def test_invalid_process_identifier_rejected(base):
    r = alg.handle_request(base, "P9", [0, 0, 0])
    assert r.status == alg.INVALID_INPUT and "Invalid process identifier" in r.reason and r.state_unchanged
    _, _, errs = parse_request(base.process_ids, "p1", [0, 0, 0], 3)   # identifiers are case-sensitive
    assert errs


def test_request_text_input_is_parsed(base):
    r = alg.handle_request(base, "P1", "1, 0, 2")
    assert r.status == alg.REQUEST_GRANTED


def test_allocation_exceeding_maximum_rejected():
    state, errs = build_state(["P0"], ["A"], [[3]], [[2]], [0])
    assert state is None and "exceeds Maximum" in errs[0]


def test_non_integer_quantities_rejected():
    for bad in (1.5, "abc", None, float("nan")):
        state, errs = build_state(["P0"], ["A"], [[bad]], [[3]], [1])
        assert state is None and errs


def test_negative_quantities_rejected_in_configuration():
    state, errs = build_state(["P0"], ["A"], [[-1]], [[3]], [1])
    assert state is None and any("negative" in e for e in errs)


def test_inconsistent_available_and_total_rejected(base):
    state, errs = build_state(base.process_ids, base.resource_ids, base.allocation, base.maximum,
                              [3, 3, 3], [10, 5, 7])
    assert state is None and "Inconsistent Available" in errs[0]


def test_available_computed_from_total(base):
    state, errs = build_state(base.process_ids, base.resource_ids, base.allocation, base.maximum,
                              None, [10, 5, 7])
    assert errs == [] and state.available == [3, 3, 2]


def test_allocation_exceeding_total_rejected():
    state, errs = build_state(["P0", "P1"], ["A"], [[2], [2]], [[3], [3]], None, [3])
    assert state is None and "exceeds Total" in errs[0]


def test_dimension_mismatch_rejected():
    state, errs = build_state(["P0", "P1"], ["A", "B"], [[1, 0]], [[1, 1], [1, 1]], [1, 1])
    assert state is None and any("2 rows" in e for e in errs)
    state, errs = build_state(["P0"], ["A", "B"], [[1]], [[1, 1]], [1, 1])
    assert state is None and errs


def test_duplicate_and_empty_identifiers_rejected():
    assert build_state(["P0", "P0"], ["A"], [[0], [0]], [[0], [0]], [1])[0] is None
    assert build_state([""], ["A"], [[0]], [[0]], [1])[0] is None
    assert build_state([], ["A"], [], [], [1])[0] is None


# ---------------- Analytical test runner used by the dashboard ----------------
def test_analytical_cases_all_pass():
    rows, sub = alg.run_analytical_tests()
    assert [r["Test Case"][:3] for r in rows] == ["TC1", "TC2", "TC3", "TC4", "TC5", "TC6"]
    assert all(r["Pass / Fail"] == "PASS" for r in rows), rows
    assert len(sub) == 12 and all(c["Result"] == "PASS" for c in sub)
