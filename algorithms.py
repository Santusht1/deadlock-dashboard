"""algorithms.py - Core Operating Systems algorithms (no Streamlit code here).

Sections
--------
1. Status labels and small vector helpers
2. Banker's Algorithm: Need matrix and safety algorithm
3. Resource-request handling (atomic: fully committed or fully rolled back)
4. Deadlock DETECTION (separate from Banker's Algorithm)
5. Recovery by process termination
6. Prevention policies (resource ordering, no hold-and-wait) + a simulator
7. Built-in example configurations
8. Analytical test cases TC1-TC6 (run against the functions above)

Functions never modify their arguments; they return new objects instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from validation import (DetectionScenario, Matrix, SystemState, Vector,
                        build_detection_scenario, build_state, parse_request)

# --------------------------------------------------------------------------
# 1. Status labels and helpers
# --------------------------------------------------------------------------
SAFE_STATE = "SAFE STATE"
UNSAFE_STATE = "UNSAFE STATE"
REQUEST_GRANTED = "REQUEST CAN BE GRANTED"
REQUEST_EXCEEDS_AVAILABLE = "REQUEST EXCEEDS AVAILABLE RESOURCES"
REQUEST_DENIED_UNSAFE = "REQUEST DENIED: UNSAFE RESULTING STATE"
DEADLOCK_DETECTED = "DEADLOCK DETECTED"
NO_DEADLOCK_DETECTED = "NO DEADLOCK DETECTED"
INVALID_INPUT = "INVALID INPUT"


def vec_leq(a: Sequence[int], b: Sequence[int]) -> bool:
    """True when a[j] <= b[j] for every j."""
    return all(x <= y for x, y in zip(a, b))


def vec_add(a: Sequence[int], b: Sequence[int]) -> Vector:
    return [x + y for x, y in zip(a, b)]


def vec_sub(a: Sequence[int], b: Sequence[int]) -> Vector:
    return [x - y for x, y in zip(a, b)]


def fmt(vec: Sequence[int]) -> str:
    return "[" + ", ".join(str(x) for x in vec) + "]"


# --------------------------------------------------------------------------
# 2. Banker's Algorithm: Need matrix and safety algorithm
# --------------------------------------------------------------------------
def calculate_need(maximum: Matrix, allocation: Matrix) -> Matrix:
    """Need[i][j] = Maximum[i][j] - Allocation[i][j]."""
    return [[m - a for m, a in zip(max_row, alloc_row)]
            for max_row, alloc_row in zip(maximum, allocation)]


@dataclass
class SafetyStep:
    step: int
    process: str
    index: int
    work_before: Vector
    need: Vector
    allocation: Vector
    work_after: Vector


@dataclass
class SafetyResult:
    need: Matrix
    initial_work: Vector
    steps: List[SafetyStep]
    finish: List[bool]
    safe_sequence: List[str]          # complete only when the state is safe
    unfinished: List[str]             # processes unable to finish
    unfinished_info: List[dict]       # why each one is stuck
    final_work: Vector
    is_safe: bool

    @property
    def status(self) -> str:
        return SAFE_STATE if self.is_safe else UNSAFE_STATE


def check_safety(state: SystemState) -> SafetyResult:
    """Banker's safety algorithm.

    1. Need = Maximum - Allocation
    2. Work = Available
    3. Finish[i] = False for all i
    4. Pick an unfinished i with Need[i] <= Work (lowest index first)
    5. Work = Work + Allocation[i]; Finish[i] = True; append i to sequence
    6. Repeat until everything finished or nobody is eligible
    """
    n = state.n_processes
    need = calculate_need(state.maximum, state.allocation)
    work = list(state.available)
    initial_work = list(work)
    finish = [False] * n
    steps: List[SafetyStep] = []
    while True:
        chosen = next((i for i in range(n) if not finish[i] and vec_leq(need[i], work)), None)
        if chosen is None:
            break
        before = list(work)
        work = vec_add(work, state.allocation[chosen])
        finish[chosen] = True
        steps.append(SafetyStep(len(steps) + 1, state.process_ids[chosen], chosen, before,
                                list(need[chosen]), list(state.allocation[chosen]), list(work)))
    is_safe = all(finish)
    unfinished_info = []
    for i in range(n):
        if not finish[i]:
            short = [state.resource_ids[j] for j in range(len(work)) if need[i][j] > work[j]]
            unfinished_info.append({"process": state.process_ids[i], "need": list(need[i]),
                                    "work": list(work), "short_of": short})
    return SafetyResult(
        need=need, initial_work=initial_work, steps=steps, finish=finish,
        safe_sequence=[s.process for s in steps] if is_safe else [],
        unfinished=[state.process_ids[i] for i in range(n) if not finish[i]],
        unfinished_info=unfinished_info, final_work=work, is_safe=is_safe)


def verify_safe_sequence(state: SystemState, sequence: Sequence[str]) -> Tuple[bool, str]:
    """Independent checker: can every process in `sequence` really finish in turn?"""
    if sorted(sequence) != sorted(state.process_ids):
        return False, "Sequence must contain every process exactly once"
    need = calculate_need(state.maximum, state.allocation)
    work = list(state.available)
    for pid in sequence:
        i = state.process_ids.index(pid)
        if not vec_leq(need[i], work):
            return False, f"{pid} cannot finish: Need {fmt(need[i])} > Work {fmt(work)}"
        work = vec_add(work, state.allocation[i])
    return True, "Every process can finish with the resources available at its turn"


# --------------------------------------------------------------------------
# 3. Resource-request handling
# --------------------------------------------------------------------------
@dataclass
class RequestResult:
    status: str
    granted: bool
    must_wait: bool                   # valid request, but resources not available yet
    invalid: bool                     # malformed or violates the process's Need
    process: str
    request: Optional[Vector]
    reason: str
    errors: List[str]
    available_before: Vector
    snapshot: SystemState             # copy of the state before the request
    tentative: Optional[SystemState]  # state after the temporary allocation
    safety: Optional[SafetyResult]    # safety analysis of the tentative state
    final_state: SystemState          # committed state, or the exact snapshot on failure
    state_unchanged: bool             # final_state == snapshot
    log: List[str] = field(default_factory=list)


def handle_request(state: SystemState, process: str, request_raw) -> RequestResult:
    """Resource-request algorithm. `state` itself is never modified.

    Order of checks (as required):
    1 process id valid -> 2 vector valid -> 3 request <= Need -> 4 request <= Available
    -> 5 temporary allocation -> 6 safety check -> 7 commit if safe / 8 restore.
    """
    snapshot = state.copy()
    log: List[str] = []

    def finish(status, reason, *, granted=False, wait=False, invalid=False, request=None,
               errors=None, tentative=None, safety=None, final=None) -> RequestResult:
        final_state = final if final is not None else snapshot.copy()
        return RequestResult(status, granted, wait, invalid, process, request, reason, errors or [],
                             list(snapshot.available), snapshot, tentative, safety, final_state,
                             final_state == snapshot, log)

    # Steps 1-2: identifier and vector
    index, request, errors = parse_request(state.process_ids, process, request_raw, state.n_resources)
    if errors:
        log.append("Steps 1-2 FAILED: " + "; ".join(errors))
        return finish(INVALID_INPUT, "; ".join(errors), invalid=True, errors=errors)
    log.append(f"Step 1 OK: '{process}' is a valid process")
    log.append(f"Step 2 OK: request {fmt(request)} has {state.n_resources} non-negative integers")

    # Step 3: request <= Need
    need = calculate_need(state.maximum, state.allocation)[index]
    over_need = [state.resource_ids[j] for j in range(len(request)) if request[j] > need[j]]
    if over_need:
        reason = (f"Request {fmt(request)} exceeds the remaining Need {fmt(need)} of {process} for "
                  f"resource(s) {', '.join(over_need)}. The process would exceed its declared "
                  f"maximum claim, so the request is invalid (it is not merely waiting).")
        log.append("Step 3 FAILED: " + reason)
        return finish(INVALID_INPUT, reason, invalid=True, request=request, errors=[reason])
    log.append(f"Step 3 OK: request {fmt(request)} <= Need {fmt(need)}")

    # Step 4: request <= Available
    short = [state.resource_ids[j] for j in range(len(request)) if request[j] > state.available[j]]
    if short:
        details = ", ".join(f"{state.resource_ids[j]}: requested {request[j]}, available {state.available[j]}"
                            for j in range(len(request)) if request[j] > state.available[j])
        reason = (f"Request {fmt(request)} exceeds Available {fmt(state.available)} ({details}). "
                  f"The request is valid (within Need), so {process} must WAIT until resources are "
                  f"released. State left unchanged.")
        log.append("Step 4 FAILED: " + reason)
        return finish(REQUEST_EXCEEDS_AVAILABLE, reason, wait=True, request=request)
    log.append(f"Step 4 OK: request {fmt(request)} <= Available {fmt(state.available)}")

    # Step 5: temporary allocation on a working copy
    working = state.copy()
    working.allocation[index] = vec_add(working.allocation[index], request)
    working.available = vec_sub(working.available, request)
    log.append(f"Step 5: temporarily allocated; Allocation[{process}] = {fmt(working.allocation[index])}, "
              f"Available = {fmt(working.available)}")

    # Step 6: safety check of the tentative state
    safety = check_safety(working)
    log.append(f"Step 6: safety algorithm on tentative state -> {safety.status}")

    # Steps 7-8: commit or restore
    if safety.is_safe:
        log.append(f"Step 7: state is safe, allocation COMMITTED (sequence {' -> '.join(safety.safe_sequence)})")
        reason = (f"Granting {fmt(request)} to {process} leaves a safe state "
                  f"(safe sequence: {' -> '.join(safety.safe_sequence)}).")
        return finish(REQUEST_GRANTED, reason, granted=True, request=request,
                      tentative=working, safety=safety, final=working)
    reason = (f"Granting {fmt(request)} to {process} would leave an UNSAFE state: "
              f"{', '.join(safety.unfinished)} could not be guaranteed to finish. "
              f"(Unsafe means deadlock is possible, not that a deadlock already exists.)")
    log.append("Step 8: state is unsafe, request DENIED and the original state restored")
    return finish(REQUEST_DENIED_UNSAFE, reason, request=request, tentative=working, safety=safety)


def find_unsafe_requests(state: SystemState, max_results: int = 20) -> List[Tuple[str, Vector]]:
    """Exhaustively find requests that satisfy Need and Available but give an unsafe state.

    Only meaningful when `state` is currently safe (otherwise returns []).
    """
    if not check_safety(state).is_safe:
        return []
    need = calculate_need(state.maximum, state.allocation)
    found: List[Tuple[str, Vector]] = []
    for i, pid in enumerate(state.process_ids):
        limits = [min(need[i][j], state.available[j]) for j in range(state.n_resources)]
        for req in product(*[range(limit + 1) for limit in limits]):
            if not any(req):
                continue
            if handle_request(state, pid, list(req)).status == REQUEST_DENIED_UNSAFE:
                found.append((pid, list(req)))
                if len(found) >= max_results:
                    return found
    return found


# --------------------------------------------------------------------------
# 4. Deadlock DETECTION (does not call the Banker's functions)
# --------------------------------------------------------------------------
@dataclass
class DetectionStep:
    step: int
    process: str
    work_before: Vector
    request: Vector
    released: Vector
    work_after: Vector


@dataclass
class DetectionResult:
    initial_work: Vector
    initial_finish: List[bool]
    steps: List[DetectionStep]
    finish: List[bool]
    deadlocked: List[str]
    final_work: Vector
    wait_cycle: Optional[List[str]]   # a circular wait among blocked processes, if any

    @property
    def deadlock_detected(self) -> bool:
        return len(self.deadlocked) > 0

    @property
    def status(self) -> str:
        return DEADLOCK_DETECTED if self.deadlock_detected else NO_DEADLOCK_DETECTED


def build_wait_for_graph(s: DetectionScenario) -> Dict[str, List[str]]:
    """Edge Pi -> Pj when Pi is blocked on a resource (request > Available) that Pj holds."""
    graph: Dict[str, List[str]] = {p: [] for p in s.process_ids}
    for i, pi in enumerate(s.process_ids):
        for r in range(len(s.resource_ids)):
            if s.request[i][r] > s.available[r]:
                for j, pj in enumerate(s.process_ids):
                    if j != i and s.allocation[j][r] > 0 and pj not in graph[pi]:
                        graph[pi].append(pj)
    return graph


def find_cycle(graph: Dict[str, List[str]]) -> Optional[List[str]]:
    """Depth-first search for a cycle; returns the cycle as a list of nodes or None."""
    visiting: List[str] = []
    done: set = set()

    def dfs(node: str) -> Optional[List[str]]:
        if node in visiting:
            return visiting[visiting.index(node):] + [node]
        if node in done:
            return None
        visiting.append(node)
        for nxt in graph[node]:
            cycle = dfs(nxt)
            if cycle:
                return cycle
        visiting.pop()
        done.add(node)
        return None

    for start in graph:
        cycle = dfs(start)
        if cycle:
            return cycle
    return None


def detect_deadlock(s: DetectionScenario) -> DetectionResult:
    """Standard detection algorithm for multiple instances per resource type.

    1. Work = Available
    2. Finish[i] = True if Allocation[i] is all zeros (a process that holds nothing
       cannot be part of a deadlock), otherwise False
    3. Find unfinished i with Request[i] <= Work
    4. Work = Work + Allocation[i]; Finish[i] = True; repeat
    5. Every process still unfinished is deadlocked (under these assumptions)
    """
    n = len(s.process_ids)
    work = list(s.available)
    finish = [all(a == 0 for a in s.allocation[i]) for i in range(n)]
    initial_finish = list(finish)
    steps: List[DetectionStep] = []
    while True:
        chosen = next((i for i in range(n) if not finish[i] and vec_leq(s.request[i], work)), None)
        if chosen is None:
            break
        before = list(work)
        work = vec_add(work, s.allocation[chosen])
        finish[chosen] = True
        steps.append(DetectionStep(len(steps) + 1, s.process_ids[chosen], before,
                                   list(s.request[chosen]), list(s.allocation[chosen]), list(work)))
    deadlocked = [s.process_ids[i] for i in range(n) if not finish[i]]
    return DetectionResult(list(s.available), initial_finish, steps, finish, deadlocked, work,
                           find_cycle(build_wait_for_graph(s)))


# --------------------------------------------------------------------------
# 5. Recovery by process termination
# --------------------------------------------------------------------------
@dataclass
class RecoveryResult:
    victim: str
    released: Vector
    before: DetectionScenario
    after: DetectionScenario
    detection_before: DetectionResult
    detection_after: DetectionResult
    consistent: bool
    note: str


def terminate_process(s: DetectionScenario, victim: str) -> RecoveryResult:
    """Terminate `victim`, release its Allocation, update Available, rerun detection."""
    if victim not in s.process_ids:
        raise ValueError(f"Unknown process '{victim}'")
    i = s.process_ids.index(victim)
    after = s.copy()
    released = list(s.allocation[i])
    after.allocation[i] = [0] * len(s.resource_ids)
    after.request[i] = [0] * len(s.resource_ids)          # a terminated process requests nothing
    after.available = vec_add(s.available, released)
    # Consistency: for each resource, sum(Allocation) + Available == Total
    consistent = all(
        sum(after.allocation[p][j] for p in range(len(s.process_ids))) + after.available[j] == s.total[j]
        for j in range(len(s.resource_ids)))
    return RecoveryResult(
        victim, released, s.copy(), after, detect_deadlock(s), detect_deadlock(after), consistent,
        f"{victim} was terminated: all work done by {victim} is lost and it must be restarted. "
        f"Released {fmt(released)} back to Available.")


def suggest_victim(s: DetectionScenario) -> Optional[str]:
    """Cheapest-victim heuristic: the deadlocked process holding the fewest resources."""
    result = detect_deadlock(s)
    if not result.deadlocked:
        return None
    return min(result.deadlocked, key=lambda p: sum(s.allocation[s.process_ids.index(p)]))


# --------------------------------------------------------------------------
# 6. Prevention policies and a small simulator
# --------------------------------------------------------------------------
@dataclass
class PolicyCheck:
    allowed: bool
    policy: str
    messages: List[str]


def check_resource_ordering(held: Sequence[int], request: Sequence[int], resource_ids: Sequence[str],
                            order: Optional[Sequence[int]] = None) -> PolicyCheck:
    """Resource ordering: a process may only request resource types ranked HIGHER than
    every type it already holds (default rank = position in `resource_ids`).
    Requesting several types in one call is fine; they are acquired in rank order.
    """
    rank = list(order) if order is not None else list(range(len(resource_ids)))
    held_idx = [j for j in range(len(held)) if held[j] > 0]
    top = max(held_idx, key=lambda j: rank[j]) if held_idx else None   # highest-ranked type held
    highest = rank[top] if top is not None else -1
    violations = []
    for j in range(len(request)):
        if request[j] > 0 and rank[j] <= highest:
            holder = resource_ids[top]
            violations.append(f"requests {resource_ids[j]} (rank {rank[j]}) while holding {holder} "
                              f"(rank {highest}); requests must go in increasing rank")
    return PolicyCheck(not violations, "Resource ordering",
                       violations or ["Request follows the global resource order"])


def check_hold_and_wait(held: Sequence[int], request: Sequence[int], maximum: Sequence[int]) -> PolicyCheck:
    """Eliminate hold-and-wait ('all at once'): a process must request its whole
    maximum claim in a single request and may hold nothing while doing so."""
    problems = []
    if any(h > 0 for h in held):
        problems.append(f"holds {fmt(held)} while requesting more (hold-and-wait)")
    if list(request) != list(maximum):
        problems.append(f"request {fmt(request)} is not the full claim {fmt(maximum)}")
    return PolicyCheck(not problems, "No hold-and-wait (all at once)",
                       problems or ["Process requests everything at once and holds nothing"])


@dataclass
class SimulationResult:
    log: List[dict]
    completed: List[str]
    rejected: List[str]
    deadlocked: List[str]
    detection: Optional[DetectionResult]


def simulate_acquisition(process_ids: Sequence[str], resource_ids: Sequence[str], total: Sequence[int],
                         plans: List[List[Vector]],
                         enforce: Optional[Callable[[int, Vector, Vector], PolicyCheck]] = None
                         ) -> SimulationResult:
    """Round-robin simulation. Each process owns a plan: a list of requests made one by one.

    A process whose plan is fully granted finishes on its next turn and releases everything.
    With `enforce`, a request that violates the policy is rejected and the process is aborted
    (it must restart with a compliant plan). If a full round makes no progress, the deadlock
    detector (section 4) examines the stuck processes.
    """
    n, m = len(process_ids), len(resource_ids)
    held = [[0] * m for _ in range(n)]
    available = list(total)
    pointer = [0] * n
    status = ["running"] * n
    log: List[dict] = []

    def note(rnd: int, i: int, action: str, detail: str) -> None:
        log.append({"Round": rnd, "Process": process_ids[i], "Action": action, "Detail": detail})

    for rnd in range(1, 101):
        progress = False
        for i in range(n):
            if status[i] != "running":
                continue
            if pointer[i] == len(plans[i]):
                available = vec_add(available, held[i])
                note(rnd, i, "FINISH", f"completes, releases {fmt(held[i])}")
                held[i], status[i], progress = [0] * m, "finished", True
                continue
            request = plans[i][pointer[i]]
            if enforce is not None:
                check = enforce(i, held[i], request)
                if not check.allowed:
                    available = vec_add(available, held[i])
                    note(rnd, i, "REJECTED", f"{check.policy}: {'; '.join(check.messages)}; "
                                             f"aborted, releases {fmt(held[i])}")
                    held[i], status[i], progress = [0] * m, "rejected", True
                    continue
            if vec_leq(request, available):
                available = vec_sub(available, request)
                held[i] = vec_add(held[i], request)
                pointer[i] += 1
                note(rnd, i, "GRANTED", f"request {fmt(request)}; holds {fmt(held[i])}")
                progress = True
            else:
                note(rnd, i, "WAITS", f"request {fmt(request)} > Available {fmt(available)}; holds {fmt(held[i])}")
        if "running" not in status or not progress:
            break

    detection, deadlocked = None, []
    if "running" in status:
        pending = [plans[i][pointer[i]] if status[i] == "running" and pointer[i] < len(plans[i]) else [0] * m
                   for i in range(n)]
        scenario = DetectionScenario("simulation", "", list(process_ids), list(resource_ids), list(total),
                                     [list(h) for h in held], pending, list(available))
        detection = detect_deadlock(scenario)
        deadlocked = detection.deadlocked
    return SimulationResult(log, [process_ids[i] for i in range(n) if status[i] == "finished"],
                            [process_ids[i] for i in range(n) if status[i] == "rejected"],
                            deadlocked, detection)


PREVENTION_PROCESSES = ["P0", "P1"]
PREVENTION_RESOURCES = ["A", "B"]
PREVENTION_TOTAL = [1, 1]


def prevention_plans(kind: str) -> List[List[Vector]]:
    """Request plans for the prevention demo (two processes, two single-instance resources).

    'unordered' : P0 asks A then B, P1 asks B then A     -> circular wait possible
    'ordered'   : both ask A then B                      -> resource ordering respected
    'incremental': each asks A then B (hold-and-wait)    -> used with the no-hold-and-wait rule
    'all_at_once': each asks {A,B} in one request        -> no hold-and-wait
    """
    plans = {
        "unordered": [[[1, 0], [0, 1]], [[0, 1], [1, 0]]],
        "ordered": [[[1, 0], [0, 1]], [[1, 0], [0, 1]]],
        "incremental": [[[1, 0], [0, 1]], [[0, 1], [1, 0]]],
        "all_at_once": [[[1, 1]], [[1, 1]]],
    }
    return [[list(r) for r in plan] for plan in plans[kind]]


def ordering_enforcer(resource_ids: Sequence[str]) -> Callable[[int, Vector, Vector], PolicyCheck]:
    return lambda i, held, request: check_resource_ordering(held, request, resource_ids)


def hold_wait_enforcer(plans: List[List[Vector]]) -> Callable[[int, Vector, Vector], PolicyCheck]:
    claims = [[sum(r[j] for r in plan) for j in range(len(plan[0]))] for plan in plans]
    return lambda i, held, request: check_hold_and_wait(held, request, claims[i])


# --------------------------------------------------------------------------
# 7. Built-in examples
# --------------------------------------------------------------------------
def example_safe_state() -> SystemState:
    """Textbook example: Total = [10, 5, 7]."""
    return SystemState(
        process_ids=["P0", "P1", "P2", "P3", "P4"], resource_ids=["A", "B", "C"],
        allocation=[[0, 1, 0], [2, 0, 0], [3, 0, 2], [2, 1, 1], [0, 0, 2]],
        maximum=[[7, 5, 3], [3, 2, 2], [9, 0, 2], [2, 2, 2], [4, 3, 3]],
        available=[3, 3, 2], total=[10, 5, 7])


SCENARIO_B_REQUEST = ("P2", [6, 0, 0])   # <= Need [6,0,0] but > Available [3,3,2]
SCENARIO_C_REQUEST = ("P4", [3, 3, 0])   # <= Need, <= Available, but leaves an unsafe state


def deadlock_examples() -> Dict[str, DetectionScenario]:
    """Detection-model examples. Each is validated by build_detection_scenario."""
    specs = [
        ("Classic two-process deadlock",
         "P0 holds A and waits for B; P1 holds B and waits for A. One instance of each resource.",
         ["P0", "P1"], ["A", "B"], [1, 1], [[1, 0], [0, 1]], [[0, 1], [1, 0]], [0, 0]),
        ("Deadlock with a bystander process",
         "Same deadlock, plus P2 which holds nothing and is only waiting. P2 is not part of the deadlocked set.",
         ["P0", "P1", "P2"], ["A", "B"], [1, 1], [[1, 0], [0, 1], [0, 0]],
         [[0, 1], [1, 0], [1, 1]], [0, 0]),
        ("Circular wait but NO deadlock (multi-instance)",
         "P0 and P1 wait for each other (a cycle in the wait-for graph), but resource A has two "
         "instances and P2 will release one, so everyone can finish.",
         ["P0", "P1", "P2"], ["A", "B"], [2, 1], [[1, 0], [0, 1], [1, 0]],
         [[0, 1], [1, 0], [0, 0]], [0, 0]),
    ]
    out: Dict[str, DetectionScenario] = {}
    for name, desc, pids, rids, total, alloc, req, avail in specs:
        scenario, errors = build_detection_scenario(name, desc, pids, rids, total, alloc, req, avail)
        if errors:  # would be a programming error in the example data
            raise ValueError(f"Example '{name}' is inconsistent: {errors}")
        out[name] = scenario
    return out


# --------------------------------------------------------------------------
# 8. Analytical test cases (TC1-TC6) - computed by calling the functions above
# --------------------------------------------------------------------------
def _row(tc: str, condition: str, actual: str, expected: str, analysis: str, passed: bool) -> dict:
    return {"Test Case": tc, "System Condition": condition, "Actual Result": actual,
            "Expected Result": expected, "Analysis / Conclusion": analysis,
            "Pass / Fail": "PASS" if passed else "FAIL"}


def _tc1() -> dict:
    state = example_safe_state()
    result = check_safety(state)
    ok, msg = verify_safe_sequence(state, result.safe_sequence)
    hand_need = [[7, 4, 3], [1, 2, 2], [6, 0, 0], [0, 1, 1], [4, 3, 1]]   # calculated by hand
    passed = result.is_safe and ok and result.need == hand_need
    return _row("TC1: Safe state", "5 processes, 3 resources, Available [3, 3, 2]",
                f"{result.status}; sequence {' -> '.join(result.safe_sequence) or 'none'}",
                f"{SAFE_STATE}; Need matches hand calculation; sequence verifiable",
                f"Need matrix {'matches' if result.need == hand_need else 'DIFFERS from'} the hand-computed values. "
                f"Independent verification: {msg}.", passed)


def _tc2() -> dict:
    state = example_safe_state()
    proc, req = SCENARIO_B_REQUEST
    r = handle_request(state, proc, req)
    passed = (r.status == REQUEST_EXCEEDS_AVAILABLE and r.must_wait and not r.invalid
              and r.state_unchanged and r.final_state == state)
    return _row("TC2: Request exceeds Available",
                f"{proc} requests {fmt(req)}; Need {fmt(calculate_need(state.maximum, state.allocation)[2])}, "
                f"Available {fmt(state.available)}",
                f"{r.status}; invalid={r.invalid}; state unchanged={r.state_unchanged}",
                f"{REQUEST_EXCEEDS_AVAILABLE} (process waits, not invalid); state unchanged",
                "The request is within Need, so it is valid; it simply cannot be satisfied now. "
                "Allocation and Available were compared with the snapshot.", passed)


def _tc3() -> dict:
    state = example_safe_state()
    proc, req = SCENARIO_C_REQUEST
    initially_safe = check_safety(state).is_safe
    r = handle_request(state, proc, req)
    need = calculate_need(state.maximum, state.allocation)[state.process_ids.index(proc)]
    preconditions = initially_safe and vec_leq(req, need) and vec_leq(req, state.available)
    in_search = (proc, req) in find_unsafe_requests(state, max_results=1000)
    passed = (preconditions and r.status == REQUEST_DENIED_UNSAFE and r.safety is not None
              and not r.safety.is_safe and r.state_unchanged and in_search)
    return _row("TC3: Request produces an unsafe state",
                f"{proc} requests {fmt(req)}; initial state safe={initially_safe}",
                f"{r.status}; tentative state "
                f"{r.safety.status if r.safety else 'n/a'}; restored={r.state_unchanged}",
                f"{REQUEST_DENIED_UNSAFE}; original Allocation/Available restored",
                f"Request satisfies Need and Available ({preconditions}) and is confirmed by exhaustive search "
                f"({in_search}); stuck after granting: {', '.join(r.safety.unfinished) if r.safety else '-'}.",
                passed)


def _tc4() -> dict:
    ex = deadlock_examples()
    classic = detect_deadlock(ex["Classic two-process deadlock"])
    bystander = detect_deadlock(ex["Deadlock with a bystander process"])
    cycle_only = detect_deadlock(ex["Circular wait but NO deadlock (multi-instance)"])
    passed = (classic.deadlocked == ["P0", "P1"] and bystander.deadlocked == ["P0", "P1"]
              and not cycle_only.deadlock_detected and cycle_only.wait_cycle is not None)
    return _row("TC4: Deadlock detected",
                "Three detection scenarios (Available [0, 0], single and multi-instance)",
                f"Classic: {classic.status} {classic.deadlocked}; bystander: {bystander.deadlocked}; "
                f"multi-instance cycle: {cycle_only.status} (cycle {cycle_only.wait_cycle})",
                f"{DEADLOCK_DETECTED} {{P0, P1}} twice; {NO_DEADLOCK_DETECTED} when the cycle can be broken",
                "The separate detector (not Banker's) finds the genuine deadlock, ignores the zero-allocation "
                "bystander, and does not report a circular wait as deadlock when another instance can be freed.",
                passed)


def _tc5() -> dict:
    rids, pids, total = PREVENTION_RESOURCES, PREVENTION_PROCESSES, PREVENTION_TOTAL
    base = simulate_acquisition(pids, rids, total, prevention_plans("unordered"))
    violating = simulate_acquisition(pids, rids, total, prevention_plans("unordered"), ordering_enforcer(rids))
    ordered = simulate_acquisition(pids, rids, total, prevention_plans("ordered"), ordering_enforcer(rids))
    inc_plans = prevention_plans("incremental")
    inc_check = check_hold_and_wait([1, 0], [0, 1], [1, 1])
    all_once = simulate_acquisition(pids, rids, total, prevention_plans("all_at_once"),
                                    hold_wait_enforcer(prevention_plans("all_at_once")))
    passed = (base.deadlocked == ["P0", "P1"] and violating.rejected == ["P1"] and not violating.deadlocked
              and not ordered.deadlocked and sorted(ordered.completed) == pids and not ordered.rejected
              and not inc_check.allowed and not all_once.deadlocked and sorted(all_once.completed) == pids)
    return _row("TC5: Prevention policy applied",
                "Two processes, resources A < B (one instance each)",
                f"No policy: deadlocked {base.deadlocked}; ordering rejects {violating.rejected}; "
                f"compliant plans complete {ordered.completed}; all-at-once completes {all_once.completed}; "
                f"incremental request allowed={inc_check.allowed}",
                "Without policy: deadlock. With ordering: violating request rejected, compliant run completes. "
                "No hold-and-wait: incremental request rejected, all-at-once completes",
                "Resource ordering removes circular wait and requesting everything at once removes "
                "hold-and-wait; both were enforced by code, not just described.", passed)


def _tc6_cases() -> List[dict]:
    """The twelve boundary / invalid-input cases of Scenario F."""
    cases: List[dict] = []

    def add(num: int, name: str, actual: str, expected: str, passed: bool) -> None:
        cases.append({"#": num, "Case": name, "Actual": actual, "Expected": expected,
                      "Result": "PASS" if passed else "FAIL"})

    base = example_safe_state()
    # 1 zero Available (valid, safe because P0 has zero Need)
    s1, e1 = build_state(["P0", "P1"], ["A", "B"], [[1, 1], [0, 0]], [[1, 1], [1, 1]], [0, 0], [1, 1])
    r1 = check_safety(s1) if s1 else None
    add(1, "Zero Available resources", f"valid={s1 is not None}; {r1.status if r1 else e1}",
        f"valid input; {SAFE_STATE}", bool(r1 and r1.is_safe and r1.safe_sequence[0] == "P0"))
    # 2 zero-Need process finishes immediately
    s2, _ = build_state(["P0", "P1"], ["A"], [[2], [0]], [[2], [3]], [1], None)
    r2 = check_safety(s2)
    add(2, "Process with zero remaining Need", f"first in sequence: {r2.safe_sequence[:1]}; {r2.status}",
        f"P0 finishes first; {SAFE_STATE}", r2.safe_sequence[:1] == ["P0"] and r2.is_safe)
    # 3 invalid process id
    r3 = handle_request(base, "P9", [0, 0, 0])
    add(3, "Invalid process identifier", r3.status, INVALID_INPUT, r3.status == INVALID_INPUT and r3.state_unchanged)
    # 4 negative request
    r4 = handle_request(base, "P1", [-1, 0, 0])
    add(4, "Negative resource request", r4.status, INVALID_INPUT, r4.status == INVALID_INPUT and r4.state_unchanged)
    # 5 wrong vector length
    r5 = handle_request(base, "P1", [1, 0])
    add(5, "Request with wrong number of entries", r5.status, INVALID_INPUT,
        r5.status == INVALID_INPUT and r5.state_unchanged)
    # 6 allocation exceeds maximum
    s6, e6 = build_state(["P0"], ["A"], [[3]], [[2]], [0], None)
    add(6, "Allocation exceeds Maximum", e6[0] if e6 else "accepted", f"{INVALID_INPUT} (rejected)",
        s6 is None and bool(e6))
    # 7 non-integer quantities
    s7, e7 = build_state(["P0"], ["A"], [[1.5]], [[3]], [1], None)
    s7b, e7b = build_state(["P0"], ["A"], [["abc"]], [[3]], [1], None)
    add(7, "Non-integer resource quantity", (e7 or ["accepted"])[0], f"{INVALID_INPUT} (rejected)",
        s7 is None and s7b is None)
    # 8 inconsistent Available and Total
    s8, e8 = build_state(base.process_ids, base.resource_ids, base.allocation, base.maximum, [3, 3, 3], [10, 5, 7])
    add(8, "Inconsistent Available and Total", (e8 or ["accepted"])[0], f"{INVALID_INPUT} (rejected)",
        s8 is None and bool(e8))
    # 9 request exceeds Need
    r9 = handle_request(base, "P1", [2, 0, 0])
    add(9, "Request exceeds Need", f"{r9.status}; invalid={r9.invalid}", f"{INVALID_INPUT}; invalid=True",
        r9.status == INVALID_INPUT and r9.invalid and r9.state_unchanged)
    # 10 request exceeds Available (waits)
    r10 = handle_request(base, *SCENARIO_B_REQUEST)
    add(10, "Request exceeds Available (within Need)", f"{r10.status}; invalid={r10.invalid}",
        f"{REQUEST_EXCEEDS_AVAILABLE}; invalid=False",
        r10.status == REQUEST_EXCEEDS_AVAILABLE and not r10.invalid and r10.state_unchanged)
    # 11 valid state where nobody can proceed
    s11, _ = build_state(["P0", "P1"], ["A", "B"], [[1, 0], [0, 1]], [[3, 3], [3, 3]], [1, 1], None)
    r11 = check_safety(s11)
    add(11, "Valid state, no process can proceed", f"{r11.status}; steps={len(r11.steps)}; stuck={r11.unfinished}",
        f"{UNSAFE_STATE}; no steps; (valid input, not an error)",
        not r11.is_safe and len(r11.steps) == 0)
    # 12 all processes completed
    s12, _ = build_state(["P0", "P1"], ["A"], [[0], [0]], [[0], [0]], None, [4])
    r12 = check_safety(s12)
    add(12, "All processes completed", f"{r12.status}; Available={s12.available}",
        f"{SAFE_STATE}; Available equals Total", r12.is_safe and s12.available == [4])
    return cases


def _tc6() -> dict:
    cases = _tc6_cases()
    ok = sum(c["Result"] == "PASS" for c in cases)
    return _row("TC6: Boundary and invalid inputs", "12 boundary / invalid cases (see detailed table)",
                f"{ok}/{len(cases)} cases behaved as expected", f"{len(cases)}/{len(cases)} cases behave as expected",
                "Valid boundaries (zero Available, zero Need, no runnable process, all finished) are accepted; "
                "invalid inputs are rejected without crashing or changing state; waiting is not invalid.",
                ok == len(cases))


def run_analytical_tests() -> Tuple[List[dict], List[dict]]:
    """Return (TC1-TC6 rows, TC6 sub-case rows). Exceptions become FAIL rows, never crashes."""
    rows = []
    for name, fn in (("TC1: Safe state", _tc1), ("TC2: Request exceeds Available", _tc2),
                     ("TC3: Request produces an unsafe state", _tc3), ("TC4: Deadlock detected", _tc4),
                     ("TC5: Prevention policy applied", _tc5), ("TC6: Boundary and invalid inputs", _tc6)):
        try:
            rows.append(fn())
        except Exception as exc:  # pragma: no cover - safety net for the UI
            rows.append(_row(name, "-", f"Exception: {exc!r}", "No exception", "Test crashed", False))
    return rows, _tc6_cases()
