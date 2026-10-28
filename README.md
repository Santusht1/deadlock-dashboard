# Deadlock Analysis and Resource Allocation Dashboard

An interactive Streamlit dashboard for an Operating Systems project. It implements
Banker's Algorithm (safety analysis and resource-request handling), a **separate**
deadlock detector, deadlock prevention policies, recovery by process termination,
and strict input validation. Everything runs locally: no database, API key, cloud
service or external AI service.

## Project structure

```
deadlock-dashboard/
├── app.py              Streamlit user interface (no algorithm logic)
├── algorithms.py       Banker's, request handling, detection, recovery, prevention, TC1-TC6 runner
├── validation.py       Input parsing/validation and the SystemState / DetectionScenario containers
├── test_algorithms.py  pytest unit tests
├── requirements.txt
├── README.md
└── .gitignore
```

## Setup on Windows 11

1. Install Python 3.10+ from python.org (tick "Add python.exe to PATH").
2. Open PowerShell and create the folder (or copy the provided one):
   ```powershell
   cd $HOME\Documents
   mkdir deadlock-dashboard
   cd deadlock-dashboard
   ```
   Place the seven files in this folder.
3. Create and activate a virtual environment:
   ```powershell
   python -m venv venv
   venv\Scripts\Activate.ps1
   ```
   If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use Command Prompt: `venv\Scripts\activate.bat`.
4. Install dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```
5. Run the dashboard (opens at http://localhost:8501):
   ```powershell
   python -m streamlit run app.py
   ```
6. Run the unit tests:
   ```powershell
   python -m pytest -v
   ```

## Using the dashboard

| Page | What it does |
|---|---|
| 1. System Configuration | Set process/resource counts and names, edit Allocation, Maximum, Available and Total. Validation runs when you press *Validate and apply*; an invalid configuration is never applied. |
| 2. Banker's Algorithm and Safety Analysis | Need matrix, SAFE/UNSAFE status, safe sequence chips, every Work update, a Work chart. |
| 3. Resource Request Simulator | Pick a process and enter a vector such as `1, 0, 2`. Shows the full transaction log, tentative state, safety analysis and rollback verification. Buttons load Scenarios B and C. |
| 4. Deadlock Detection | Three examples, outstanding Request matrix, resource-allocation graph, Work updates, deadlocked set, circular-wait explanation. |
| 5. Prevention and Recovery | Resource ordering and no-hold-and-wait shown side by side with the original run; terminate a process and re-run detection. |
| 6. Test Cases and Results | *Run All Tests* produces TC1-TC6 (CSV export). A separate button runs the pytest suite. |
| 7. About the Algorithms | Short theory summary. |

Sidebar: navigation, current system summary and a **Reset to example** button.

## Testing each required scenario in the UI

| Scenario | Steps | Expected result |
|---|---|---|
| A. Safe state | Page 2 with the default example | `SAFE STATE`, sequence P1 → P3 → P0 → P2 → P4 (other safe sequences exist), 5 steps shown |
| B. Request exceeds Available | Page 3, click *Load Scenario B*, then *Submit request* (P2 requests `6, 0, 0`; Need `[6,0,0]`, Available `[3,3,2]`) | `REQUEST EXCEEDS AVAILABLE RESOURCES`; labelled as waiting, not invalid; Allocation and Available unchanged |
| C. Unsafe resulting state | Page 3, click *Load Scenario C*, then *Submit request* (P4 requests `3, 3, 0`) | `REQUEST DENIED: UNSAFE RESULTING STATE`; tentative state shows Available `[0, 0, 2]` and `UNSAFE STATE`; rollback verification confirms the original state |
| D. Deadlock detection | Page 4, "Classic two-process deadlock" | `DEADLOCK DETECTED`, deadlocked set `P0, P1`. Switch to the third example: circular wait exists but `NO DEADLOCK DETECTED` |
| E. Prevention and recovery | Page 5, Prevention tab, then Recovery tab: select a victim and press *Terminate* | Original run deadlocks; ordering run completes; after termination Available is updated, consistency check passes, `NO DEADLOCK DETECTED` |
| F. Boundary and invalid inputs | Page 3: tick *Type the process identifier manually* and use `P9`; use `-1, 0, 0`, `1, 0`, `2, 0, 0` for P1. Page 1: try allocation > maximum or inconsistent Available. Page 6: TC6 table | `INVALID INPUT` with an actionable message, no crash, no state change. Valid boundaries (zero Available, zero Need) are accepted |

How the unsafe request was verified: `find_unsafe_requests` enumerates every request that is within Need and within Available for a safe state, runs the full request algorithm on each, and returns those that lead to an unsafe state. `(P4, [3,3,0])` is in that list, and TC3 and a unit test re-check it.

## Algorithms

* **Need** = Maximum − Allocation. **Available** = Total − Σ Allocation (when Total is given).
* **Safety algorithm**: Work = Available; repeatedly pick an unfinished process with Need ≤ Work (lowest index first), add its Allocation to Work. Safe if all processes finish.
* **Request algorithm** (atomic): valid process → valid vector → Request ≤ Need (else *invalid*) → Request ≤ Available (else *wait*) → temporary allocation on a copy → safety check → commit if safe, otherwise the exact snapshot is returned.
* **Detection algorithm** (does not call Banker's code): Work = Available; Finish[i] = True only if Allocation[i] is all zeros; find unfinished i with Request[i] ≤ Work; release its Allocation; the processes still unfinished at the end are deadlocked.
* **Recovery**: terminate a victim, add its Allocation to Available, clear its row, re-run detection, check ΣAllocation + Available = Total.
* **Prevention**: resource ordering (requests must go to a strictly higher-ranked resource type than any held) and no-hold-and-wait (request the full claim at once while holding nothing).

## Testing

* **Unit tests (pytest):** `python -m pytest -v` runs `test_algorithms.py`. The tests assert specific results (for example that each step of a safe sequence satisfies Need ≤ Work).
* **Analytical results (dashboard page 6):** TC1-TC6 are computed by calling the same functions; Actual Result is not hard-coded, and Pass/Fail is an automatic comparison. They complement, but are not the same as, the pytest results.

Test status in the environment where this code was written: 44 pytest tests passed, and the dashboard was smoke-tested with Streamlit's `AppTest`. Run them on your own machine before your demonstration.

## Educational notes

**What is a deadlock?** A set of processes, each waiting for a resource held by another process in the set, so none can proceed.

**Four necessary conditions:** mutual exclusion, hold and wait, no preemption, circular wait. All four must hold simultaneously.

**Prevention vs avoidance vs detection vs recovery.** Prevention removes one of the four conditions by design. Avoidance (Banker's) lets all four conditions be possible but only grants requests that keep the state safe. Detection allows deadlock and finds it afterwards. Recovery breaks a detected deadlock (terminate processes or preempt resources).

**Need matrix.** What each process may still request: Maximum − Allocation.

**Safe sequences.** An order of all processes such that each can finish using Available plus what earlier processes released. A state is safe if at least one exists. Several may exist.

**Unsafe does not mean deadlocked.** Unsafe means no guaranteed order exists, so a deadlock is possible if processes ask for their maximum. Processes may release resources earlier and avoid it. This dashboard never labels an unsafe state as a deadlock.

**Why request handling and detection are separate.** Banker's reasons about declared maximum claims and prevents risky states. Detection looks at actual outstanding requests and finds deadlock that already exists. They use different inputs (Need vs Request) and answer different questions. The detector here does not call the safety function (a unit test enforces this).

**Detection assumptions.**
* Finish[i] starts True for processes holding nothing; they cannot be part of a deadlock (they can still be blocked).
* A process that obtains its requested resources will finish and release everything.
* The result describes the current requests only.
* With multiple instances per type, a cycle in the wait-for graph is necessary but not sufficient for deadlock; the detection algorithm decides.

**Limitations of the simulation.** Fixed numbers of processes and resources; reusable resources only; processes must declare maximum claims; the request simulator checks one request at a time; the recovery model only terminates processes (no preemption or rollback); prevention demos use two processes and single-instance resources; no real scheduling or timing.

## AI usage record (template)

Fill in this table yourself. The fields below are intentionally left blank so that nothing is claimed that you have not done.

| Field | Entry |
|---|---|
| AI tool used | *(name and version, for example Claude, date used)* |
| Purpose | *(what you asked it to help with)* |
| Output generated | *(files / explanations it produced)* |
| Student verification | *(only what you actually did, for example: "ran pytest on my machine", "traced the safe sequence by hand", "read every file and can explain it")* |

Suggested verification you can genuinely perform: hand-compute the Need matrix and one safe sequence; run `python -m pytest -v`; submit Scenarios B and C and confirm the state is unchanged; change a number in the example and predict the result before running.

## Six-minute demonstration checklist

1. **(0:00-0:45) Introduce.** Purpose, the seven pages, everything runs locally. Show the sidebar.
2. **(0:45-2:00) Safe state.** Page 2: explain Allocation, Maximum, Need; show Work updates and the safe sequence; mention other safe sequences exist.
3. **(2:00-3:15) Denied request.** Page 3: Scenario B (must wait, state unchanged), then Scenario C (unsafe, denied, rollback verified).
4. **(3:15-4:15) Separate deadlock.** Page 4: classic deadlock; explain why Banker's is not used; show the third example (circular wait without deadlock).
5. **(4:15-5:15) Prevention or recovery.** Page 5: resource ordering side by side, then terminate a victim and show the consistent state and the side effect (lost work).
6. **(5:15-6:00) Boundary case.** Submit `-1, 0, 0` or `P9` for an `INVALID INPUT` message; show page 6 *Run All Tests* and mention the pytest results.

## Likely viva questions

1. **Is an unsafe state a deadlock?** No. Unsafe means deadlock is possible; deadlock means processes are already blocked forever.
2. **Why is Banker's Algorithm called avoidance?** It grants a request only if the resulting state is safe, so the system never enters a state from which deadlock cannot be avoided.
3. **What happens when Request > Need?** The process exceeds its declared maximum claim; the request is an error and is rejected.
4. **What happens when Request ≤ Need but Request > Available?** The request is valid but the process must wait for other processes to release resources.
5. **Is the safe sequence unique?** No; any order in which every process can finish is valid. The tool reports the first it finds.
6. **What is the time complexity of the safety algorithm?** O(m × n²) for n processes and m resource types.
7. **Why does the detector start with Finish = True for processes with zero allocation?** They hold nothing, so they cannot be holding up anyone else; they are not part of a deadlock.
8. **Is a cycle in the resource-allocation graph always a deadlock?** Only with single-instance resources. With multiple instances it is necessary but not sufficient.
9. **How does resource ordering prevent deadlock?** It makes circular wait impossible: every wait goes from a lower to a higher rank, so a cycle cannot form, provided every request obeys the order.
10. **What is the cost of eliminating hold-and-wait?** Lower resource utilization and possible starvation of processes needing many resources.
11. **What are the side effects of recovery by termination?** Lost work, possible inconsistent data, the need to restart the process, and the question of which victim to choose.
12. **Why is the request transaction atomic?** The change is made on a copy and only committed if safe; otherwise the original snapshot is kept, so no partial allocation is ever left.
