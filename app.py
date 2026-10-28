"""app.py - Streamlit user interface. All algorithm logic lives in algorithms.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import algorithms as alg
import validation as val

st.set_page_config(page_title="Deadlock Analysis and Resource Allocation Dashboard",
                   page_icon="🔒", layout="wide")

PAGES = ["1. System Configuration", "2. Banker's Algorithm and Safety Analysis",
         "3. Resource Request Simulator", "4. Deadlock Detection",
         "5. Deadlock Prevention and Recovery", "6. Test Cases and Results", "7. About the Algorithms"]
MODE_TOTAL = "Enter Total (Available is computed)"
MODE_AVAIL = "Enter Available directly (no Total)"
MODE_BOTH = "Enter both (consistency is checked)"
MODES = [MODE_TOTAL, MODE_AVAIL, MODE_BOTH]


# --------------------------------------------------------------------------
# Small display helpers
# --------------------------------------------------------------------------
def matrix_df(matrix: Sequence[Sequence[int]], rows: Sequence[str], cols: Sequence[str]) -> pd.DataFrame:
    frame = pd.DataFrame(matrix, index=list(rows), columns=list(cols))
    frame.index.name = "Process"
    return frame


def vector_df(vec: Sequence[int], cols: Sequence[str], label: str) -> pd.DataFrame:
    return pd.DataFrame([list(vec)], index=[label], columns=list(cols))


def banner(label: str, kind: str, detail: str = "") -> None:
    """Coloured status banner. kind: success | error | warning | info."""
    getattr(st, kind)(f"**{label}**" + (f"  \n{detail}" if detail else ""))


def chain_html(names: Sequence[str], color: str = "#1f7a3d") -> str:
    chips = [f"<span style='background:{color};color:white;padding:6px 14px;border-radius:16px;"
             f"font-weight:600'>{n}</span>" for n in names]
    return "<div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap'>" + \
           "<span style='margin:0 6px'>&rarr;</span>".join(chips) + "</div>"


def numeric_config(cols: Sequence[str]) -> Dict[str, object]:
    return {c: st.column_config.NumberColumn(c, step=1, format="%d") for c in cols}


# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
def draft_from_state(state: val.SystemState) -> dict:
    total = state.total if state.total is not None else [
        sum(state.allocation[i][j] for i in range(state.n_processes)) + state.available[j]
        for j in range(state.n_resources)]
    return {"n_proc": state.n_processes, "n_res": state.n_resources,
            "process_ids": list(state.process_ids), "resource_ids": list(state.resource_ids),
            "allocation": [list(r) for r in state.allocation], "maximum": [list(r) for r in state.maximum],
            "available": list(state.available), "total": list(total),
            "mode": MODE_BOTH if state.total is not None else MODE_AVAIL}


def set_system(state: val.SystemState) -> None:
    """Commit a (validated) state and rebuild the editable draft. Bumping `version`
    gives every widget on the configuration page a fresh key, so no stale edits survive."""
    st.session_state.cfg = state.copy()
    st.session_state.draft = draft_from_state(state)
    st.session_state.version = st.session_state.get("version", 0) + 1
    st.session_state.req_result = None


def reset_to_example() -> None:
    set_system(alg.example_safe_state())
    st.session_state.pop("rec_loaded", None)


def load_request_scenario(process: str, request: List[int]) -> None:
    """Callback for the Scenario B / C buttons: load the example system and pre-fill the form."""
    set_system(alg.example_safe_state())
    st.session_state.req_manual = False
    st.session_state.req_proc = process
    st.session_state.req_text = ", ".join(str(x) for x in request)


def init_state() -> None:
    if "cfg" not in st.session_state:
        set_system(alg.example_safe_state())
    st.session_state.setdefault("req_text", "0, 0, 0")
    st.session_state.setdefault("req_manual", False)
    st.session_state.setdefault("analytical", None)
    st.session_state.setdefault("pytest_output", None)


def resize_draft(draft: dict, n: int, m: int) -> None:
    """Grow/shrink the draft; new cells are 0 and new identifiers get default names."""
    draft["process_ids"] = (draft["process_ids"] + [f"P{k}" for k in range(len(draft["process_ids"]), n)])[:n]
    draft["resource_ids"] = (draft["resource_ids"] +
                             [chr(65 + k) if k < 26 else f"R{k}" for k in range(len(draft["resource_ids"]), m)])[:m]
    for key in ("allocation", "maximum"):
        rows = [(row + [0] * m)[:m] for row in draft[key]]
        draft[key] = (rows + [[0] * m for _ in range(n)])[:n]
    draft["available"] = (draft["available"] + [0] * m)[:m]
    draft["total"] = (draft["total"] + [0] * m)[:m]
    draft["n_proc"], draft["n_res"] = n, m


def on_dims_change() -> None:
    ver = st.session_state.version
    resize_draft(st.session_state.draft, int(st.session_state[f"n_proc_{ver}"]),
                 int(st.session_state[f"n_res_{ver}"]))
    st.session_state.version += 1


# --------------------------------------------------------------------------
# Page 1: System configuration
# --------------------------------------------------------------------------
def page_config() -> None:
    st.header("1. System Configuration")
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)
    draft, ver = st.session_state.draft, st.session_state.version

    c1, c2 = st.columns(2)
    c1.number_input("Number of processes", 1, 10, value=draft["n_proc"], step=1,
                    key=f"n_proc_{ver}", on_change=on_dims_change)
    c2.number_input("Number of resource types", 1, 8, value=draft["n_res"], step=1,
                    key=f"n_res_{ver}", on_change=on_dims_change)
    st.caption("Changing a count rebuilds the tables below (unsaved edits are discarded). "
               "Edit the tables, then press **Validate and apply**.")

    with st.form(f"config_form_{ver}"):
        pid_text = st.text_input("Process identifiers (comma-separated)", ", ".join(draft["process_ids"]))
        rid_text = st.text_input("Resource identifiers (comma-separated)", ", ".join(draft["resource_ids"]))
        mode = st.radio("How is the resource state specified?", MODES, index=MODES.index(draft["mode"]))
        pids, rids = draft["process_ids"], draft["resource_ids"]
        cfg_cols = numeric_config(rids)
        st.markdown("**Allocation matrix** (units currently held)")
        alloc_df = st.data_editor(matrix_df(draft["allocation"], pids, rids), key=f"alloc_{ver}",
                                  column_config=cfg_cols)
        st.markdown("**Maximum-demand matrix**")
        max_df = st.data_editor(matrix_df(draft["maximum"], pids, rids), key=f"max_{ver}",
                                column_config=cfg_cols)
        v1, v2 = st.columns(2)
        with v1:
            st.markdown("**Available vector** (used in modes 2 and 3)")
            avail_df = st.data_editor(vector_df(draft["available"], rids, "Available"), key=f"avail_{ver}",
                                      column_config=cfg_cols)
        with v2:
            st.markdown("**Total vector** (used in modes 1 and 3)")
            total_df = st.data_editor(vector_df(draft["total"], rids, "Total"), key=f"total_{ver}",
                                      column_config=cfg_cols)
        submitted = st.form_submit_button("Validate and apply configuration", type="primary")

    if submitted:
        new_pids, new_rids = val.split_tokens(pid_text), val.split_tokens(rid_text)
        count_errors = []
        if len(new_pids) != len(pids):
            count_errors.append(f"You entered {len(new_pids)} process identifiers but the tables have "
                                f"{len(pids)} rows. Change 'Number of processes' above instead.")
        if len(new_rids) != len(rids):
            count_errors.append(f"You entered {len(new_rids)} resource identifiers but the tables have "
                                f"{len(rids)} columns. Change 'Number of resource types' above instead.")
        if count_errors:
            banner(alg.INVALID_INPUT, "error", "The configuration was NOT applied:")
            for message in count_errors:
                st.error(message)
        else:
            avail_raw = avail_df.values.tolist()[0] if mode != MODE_TOTAL else None
            total_raw = total_df.values.tolist()[0] if mode != MODE_AVAIL else None
            state, errors = val.build_state(new_pids, new_rids, alloc_df.values.tolist(), max_df.values.tolist(),
                                            avail_raw, total_raw)
            if errors:
                banner(alg.INVALID_INPUT, "error", "The configuration was NOT applied:")
                for message in errors:
                    st.error(message)
            else:
                set_system(state)
                st.session_state.draft["mode"] = mode
                st.session_state.flash = "Configuration validated and applied."
                st.rerun()

    st.divider()
    cfg: val.SystemState = st.session_state.cfg
    st.subheader("Active configuration")
    st.latex(r"Need[i][j] = Maximum[i][j] - Allocation[i][j]")
    st.latex(r"Available[j] = Total[j] - \sum_{i} Allocation[i][j]")
    left, right = st.columns(2)
    left.markdown("**Need matrix** (computed)")
    left.dataframe(matrix_df(alg.calculate_need(cfg.maximum, cfg.allocation), cfg.process_ids, cfg.resource_ids))
    allocated = [sum(cfg.allocation[i][j] for i in range(cfg.n_processes)) for j in range(cfg.n_resources)]
    summary = pd.DataFrame({"Allocated": allocated, "Available": cfg.available,
                            "Total": cfg.total if cfg.total is not None else [a + b for a, b in zip(allocated, cfg.available)]},
                           index=cfg.resource_ids).T
    right.markdown("**Resource summary**" + ("" if cfg.total is not None else " (Total = Allocated + Available)"))
    right.dataframe(summary)
    m1, m2, m3 = st.columns(3)
    m1.metric("Processes", cfg.n_processes)
    m2.metric("Resource types", cfg.n_resources)
    m3.metric("Available vector", alg.fmt(cfg.available))


# --------------------------------------------------------------------------
# Page 2: Banker's algorithm and safety analysis
# --------------------------------------------------------------------------
def safety_steps_table(result: alg.SafetyResult, cfg: val.SystemState) -> pd.DataFrame:
    rows = [{"Step": 0, "Process selected": "-", "Check (Need <= Work)": "-",
             "Work before": "-", "+ Allocation": "-", "Work after": alg.fmt(result.initial_work)}]
    for s in result.steps:
        rows.append({"Step": s.step, "Process selected": s.process,
                     "Check (Need <= Work)": f"{alg.fmt(s.need)} <= {alg.fmt(s.work_before)}",
                     "Work before": alg.fmt(s.work_before), "+ Allocation": alg.fmt(s.allocation),
                     "Work after": alg.fmt(s.work_after)})
    return pd.DataFrame(rows)


def work_chart(result: alg.SafetyResult, rids: Sequence[str]) -> go.Figure:
    labels = ["Initial"] + [f"after {s.process}" for s in result.steps]
    series = [result.initial_work] + [s.work_after for s in result.steps]
    fig = go.Figure()
    for j, rid in enumerate(rids):
        fig.add_trace(go.Scatter(x=labels, y=[v[j] for v in series], mode="lines+markers", name=f"Work[{rid}]"))
    fig.update_layout(title="Work vector as processes complete", height=320, margin=dict(t=50, b=20),
                      yaxis_title="Units")
    return fig


def page_safety() -> None:
    st.header("2. Banker's Algorithm and Safety Analysis")
    cfg: val.SystemState = st.session_state.cfg
    result = alg.check_safety(cfg)
    c1, c2, c3 = st.columns(3)
    c1.markdown("**Allocation**")
    c1.dataframe(matrix_df(cfg.allocation, cfg.process_ids, cfg.resource_ids))
    c2.markdown("**Maximum**")
    c2.dataframe(matrix_df(cfg.maximum, cfg.process_ids, cfg.resource_ids))
    c3.markdown("**Need = Maximum - Allocation**")
    c3.dataframe(matrix_df(result.need, cfg.process_ids, cfg.resource_ids))
    st.markdown("**Available (initial Work):** " + alg.fmt(cfg.available))

    if result.is_safe:
        banner(alg.SAFE_STATE, "success", f"Safe sequence: {' → '.join(result.safe_sequence)}")
        st.markdown(chain_html(result.safe_sequence), unsafe_allow_html=True)
    else:
        banner(alg.UNSAFE_STATE, "error", "No complete safe sequence exists from this state.")
        if result.safe_sequence == [] and result.steps:
            st.markdown("Processes that could finish before the search got stuck (NOT a safe sequence):")
            st.markdown(chain_html([s.process for s in result.steps], "#b36b00"), unsafe_allow_html=True)
        st.warning("**Unsafe is not the same as deadlocked.** An unsafe state means the system *may* "
                   "deadlock if processes request their maximum claims. Deadlock detection (page 4) is a "
                   "separate analysis.")
        for info in result.unfinished_info:
            st.write(f"- **{info['process']}** cannot finish: Need {alg.fmt(info['need'])} > "
                     f"Work {alg.fmt(info['work'])} (short of {', '.join(info['short_of'])})")

    st.subheader("Intermediate steps")
    st.dataframe(safety_steps_table(result, cfg), hide_index=True)
    if result.steps:
        st.plotly_chart(work_chart(result, cfg.resource_ids))
    with st.expander("Algorithm"):
        st.markdown("1. Need = Maximum − Allocation  \n2. Work = Available; Finish[i] = False  \n"
                    "3. Find unfinished i with Need[i] ≤ Work (lowest index first)  \n"
                    "4. Work = Work + Allocation[i]; Finish[i] = True; append i  \n"
                    "5. Repeat; SAFE if every process finishes, otherwise UNSAFE.  \n\n"
                    "More than one safe sequence can exist; this tool reports the first one found.")


# --------------------------------------------------------------------------
# Page 3: Resource request simulator
# --------------------------------------------------------------------------
def show_request_result(res: alg.RequestResult, rids: Sequence[str]) -> None:
    if res.granted:
        banner(alg.REQUEST_GRANTED, "success", res.reason + " The allocation was committed.")
    elif res.must_wait:
        banner(alg.REQUEST_EXCEEDS_AVAILABLE, "warning", res.reason)
    elif res.status == alg.REQUEST_DENIED_UNSAFE:
        banner(alg.REQUEST_DENIED_UNSAFE, "error", res.reason)
    else:
        banner(alg.INVALID_INPUT, "error", "The request is malformed or breaks the Banker's rules:")
        for message in (res.errors or [res.reason]):
            st.error(message)

    m1, m2, m3 = st.columns(3)
    m1.metric("Process", res.process)
    m2.metric("Requested resources", alg.fmt(res.request) if res.request is not None else "n/a")
    m3.metric("Available before request", alg.fmt(res.available_before))

    if res.must_wait:
        st.info("**Waiting vs invalid:** this request is *valid* (it does not exceed the process's Need). "
                "It just cannot be satisfied right now, so the process waits. An *invalid* request is one "
                "that is malformed or exceeds Need.")
    elif res.invalid:
        st.info("**Invalid vs waiting:** an invalid request is rejected outright; it is never queued.")

    st.markdown("**Transaction log**")
    for line in res.log:
        st.write("- " + line)

    if res.tentative is not None:
        st.markdown("**Tentative state (after temporary allocation)**")
        t1, t2 = st.columns(2)
        t1.dataframe(matrix_df(res.tentative.allocation, res.tentative.process_ids, rids))
        t2.dataframe(vector_df(res.tentative.available, rids, "Available"))
        if res.safety is not None:
            if res.safety.is_safe:
                st.success(f"{alg.SAFE_STATE}: sequence {' → '.join(res.safety.safe_sequence)}")
            else:
                st.error(f"{alg.UNSAFE_STATE}: {', '.join(res.safety.unfinished)} cannot finish")
            st.dataframe(safety_steps_table(res.safety, res.tentative), hide_index=True)

    if not res.granted:
        st.markdown("**Rollback verification**")
        same_alloc = res.final_state.allocation == res.snapshot.allocation
        same_avail = res.final_state.available == res.snapshot.available
        b1, b2 = st.columns(2)
        b1.markdown("Original (snapshot)")
        b1.dataframe(matrix_df(res.snapshot.allocation, res.snapshot.process_ids, rids))
        b1.dataframe(vector_df(res.snapshot.available, rids, "Available"))
        b2.markdown("Restored state")
        b2.dataframe(matrix_df(res.final_state.allocation, res.final_state.process_ids, rids))
        b2.dataframe(vector_df(res.final_state.available, rids, "Available"))
        if same_alloc and same_avail:
            st.success("Verified: Allocation and Available are identical to the original. "
                       "No partial allocation was left behind.")
        else:  # should never happen
            st.error("State differs from the snapshot!")


def page_request() -> None:
    st.header("3. Resource Request Simulator")
    cfg: val.SystemState = st.session_state.cfg
    need = alg.calculate_need(cfg.maximum, cfg.allocation)
    c1, c2 = st.columns(2)
    c1.markdown("**Need matrix**")
    c1.dataframe(matrix_df(need, cfg.process_ids, cfg.resource_ids))
    c2.markdown("**Allocation matrix**")
    c2.dataframe(matrix_df(cfg.allocation, cfg.process_ids, cfg.resource_ids))
    st.markdown("**Available:** " + alg.fmt(cfg.available))

    st.subheader("Request")
    b, c = alg.SCENARIO_B_REQUEST, alg.SCENARIO_C_REQUEST
    s1, s2 = st.columns(2)
    s1.button(f"Load Scenario B: {b[0]} requests {alg.fmt(b[1])} (exceeds Available)",
              on_click=load_request_scenario, args=(b[0], b[1]))
    s2.button(f"Load Scenario C: {c[0]} requests {alg.fmt(c[1])} (unsafe result)",
              on_click=load_request_scenario, args=(c[0], c[1]))
    st.caption("Both buttons load the default example system. Scenario C was verified by exhaustive search "
               "(see page 6).")

    manual = st.checkbox("Type the process identifier manually (to test invalid identifiers)", key="req_manual")
    if manual:
        process = st.text_input("Process identifier", value=st.session_state.get("req_proc", cfg.process_ids[0]),
                                key="req_proc_text")
    else:
        if st.session_state.get("req_proc") not in cfg.process_ids:
            st.session_state.req_proc = cfg.process_ids[0]
        process = st.selectbox("Process", cfg.process_ids, key="req_proc")
    request_text = st.text_input(f"Request vector for resources ({', '.join(cfg.resource_ids)}), "
                                 "comma-separated", key="req_text")

    if st.button("Submit request", type="primary"):
        result = alg.handle_request(cfg, process, request_text)
        if result.granted:
            set_system(result.final_state)       # commit (only when the result is safe)
        st.session_state.req_result = result
        st.session_state.req_committed = result.granted
        if result.granted:
            st.rerun()

    result = st.session_state.get("req_result")
    if result is not None:
        st.divider()
        show_request_result(result, cfg.resource_ids)
        if result.granted:
            st.caption("The grant is now part of the live system. Use **Reset to example** in the sidebar to start over.")


# --------------------------------------------------------------------------
# Page 4: Deadlock detection
# --------------------------------------------------------------------------
def rag_figure(s: val.DetectionScenario, deadlocked: Sequence[str] = ()) -> go.Figure:
    """Resource-allocation graph: blue arrow R->P = allocated, red arrow P->R = waiting for."""
    n, m = len(s.process_ids), len(s.resource_ids)
    py = [1 - (i + 0.5) / n for i in range(n)]
    ry = [1 - (j + 0.5) / m for j in range(m)]
    fig = go.Figure()
    for i in range(n):
        for j in range(m):
            if s.allocation[i][j] > 0:     # resource -> process (assignment edge)
                fig.add_annotation(x=0, y=py[i] - 0.015, ax=1, ay=ry[j] - 0.015, xref="x", yref="y",
                                   axref="x", ayref="y", showarrow=True, arrowhead=3, arrowwidth=2,
                                   arrowcolor="#1f5fbf", standoff=22, startstandoff=22)
                fig.add_trace(go.Scatter(x=[0.38], y=[(py[i] + ry[j]) / 2 - 0.015], mode="text",
                                         text=[f"x{s.allocation[i][j]}"], textfont=dict(color="#1f5fbf"),
                                         showlegend=False, hoverinfo="skip"))
            if s.request[i][j] > 0:        # process -> resource (request edge)
                fig.add_annotation(x=1, y=ry[j] + 0.015, ax=0, ay=py[i] + 0.015, xref="x", yref="y",
                                   axref="x", ayref="y", showarrow=True, arrowhead=3, arrowwidth=2,
                                   arrowcolor="#c0392b", standoff=22, startstandoff=22)
                fig.add_trace(go.Scatter(x=[0.62], y=[(py[i] + ry[j]) / 2 + 0.015], mode="text",
                                         text=[f"x{s.request[i][j]}"], textfont=dict(color="#c0392b"),
                                         showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=[0] * n, y=py, mode="markers+text", text=s.process_ids,
                             marker=dict(size=46, symbol="circle",
                                         color=["#c0392b" if p in deadlocked else "#7f8c8d" for p in s.process_ids]),
                             textfont=dict(color="white"), name="Process", hoverinfo="text"))
    fig.add_trace(go.Scatter(x=[1] * m, y=ry, mode="markers+text",
                             text=[f"{r} ({s.total[j]})" for j, r in enumerate(s.resource_ids)],
                             marker=dict(size=46, symbol="square", color="#2c3e50"),
                             textfont=dict(color="white"), name="Resource (total instances)", hoverinfo="text"))
    fig.update_xaxes(visible=False, range=[-0.2, 1.2])
    fig.update_yaxes(visible=False, range=[-0.05, 1.05])
    fig.update_layout(height=140 + 80 * max(n, m), margin=dict(l=10, r=10, t=30, b=10),
                      title="Resource-allocation graph (blue R→P = held, red P→R = waiting; red process = deadlocked)")
    return fig


def detection_steps_table(res: alg.DetectionResult) -> pd.DataFrame:
    rows = [{"Step": 0, "Process finished": "-", "Request <= Work?": "-", "Work before": "-",
             "+ Released Allocation": "-", "Work after": alg.fmt(res.initial_work)}]
    for s in res.steps:
        rows.append({"Step": s.step, "Process finished": s.process,
                     "Request <= Work?": f"{alg.fmt(s.request)} <= {alg.fmt(s.work_before)}",
                     "Work before": alg.fmt(s.work_before), "+ Released Allocation": alg.fmt(s.released),
                     "Work after": alg.fmt(s.work_after)})
    return pd.DataFrame(rows)


def show_detection(s: val.DetectionScenario, res: alg.DetectionResult) -> None:
    pids, rids = s.process_ids, s.resource_ids
    c1, c2, c3 = st.columns(3)
    c1.markdown("**Allocation**")
    c1.dataframe(matrix_df(s.allocation, pids, rids))
    c2.markdown("**Outstanding Request**")
    c2.dataframe(matrix_df(s.request, pids, rids))
    c3.markdown("**Total / Available**")
    c3.dataframe(pd.DataFrame([s.total, s.available], index=["Total", "Available"], columns=rids))
    st.plotly_chart(rag_figure(s, res.deadlocked))

    st.markdown("**Initial Finish flags** (True = holds nothing, cannot be part of a deadlock): " +
                ", ".join(f"{p}={f}" for p, f in zip(pids, res.initial_finish)))
    st.dataframe(detection_steps_table(res), hide_index=True)

    if res.deadlock_detected:
        banner(alg.DEADLOCK_DETECTED, "error", f"Deadlocked processes: {', '.join(res.deadlocked)}")
        pending = [f"{p} holds {alg.fmt(s.allocation[pids.index(p)])} and waits for "
                   f"{alg.fmt(s.request[pids.index(p)])}" for p in res.deadlocked]
        st.markdown("**Why this is a deadlock:** after every process that *can* finish has finished "
                    f"(Work = {alg.fmt(res.final_work)}), each remaining process still needs more than Work, "
                    "and the only processes that could release those resources are themselves stuck.")
        for line in pending:
            st.write("- " + line)
    else:
        banner(alg.NO_DEADLOCK_DETECTED, "success", "Every process can finish in some order: "
               + " → ".join(st_.process for st_ in res.steps))
    if res.wait_cycle:
        cycle_text = " → ".join(res.wait_cycle)
        if res.deadlock_detected:
            st.info(f"Circular wait found in the wait-for graph: {cycle_text}. Here it is also a confirmed deadlock.")
        else:
            st.warning(f"A circular wait exists ({cycle_text}) but it is **not** a deadlock: with multiple "
                       "instances per resource type, another process can still release a unit and break the cycle.")


def page_detection() -> None:
    st.header("4. Deadlock Detection")
    st.caption("Detection is a separate algorithm. It uses Allocation, outstanding Request and Available; "
               "it does **not** call Banker's Algorithm and does not use Maximum or Need.")
    examples = alg.deadlock_examples()
    name = st.selectbox("Example scenario", list(examples), key="det_choice")
    scenario = examples[name]
    st.write(scenario.description)
    show_detection(scenario, alg.detect_deadlock(scenario))
    with st.expander("Assumptions behind the Finish initialization"):
        st.markdown(
            "- `Work = Available`.\n"
            "- `Finish[i] = True` when `Allocation[i]` is all zeros: a process holding nothing cannot be "
            "holding up anyone else, so it is not counted as deadlocked (it may still be blocked, "
            "like P2 in the bystander example).\n"
            "- `Finish[i] = False` otherwise; it can finish if its outstanding `Request[i] <= Work`.\n"
            "- Assumes a process that gets what it requested will run to completion and release everything.\n"
            "- The result is a snapshot of *current* requests, not a prediction of future ones.")
    with st.expander("Circular wait vs confirmed deadlock"):
        st.markdown(
            "- **Circular wait** is one of the four necessary conditions: a cycle of processes each waiting "
            "for a resource held by the next.\n"
            "- With **single-instance** resources, a cycle in the resource-allocation graph *is* a deadlock.\n"
            "- With **multiple instances**, a cycle is necessary but **not sufficient**: a process outside "
            "the cycle may release an instance. Only the detection algorithm (does everyone eventually "
            "finish?) confirms the deadlock. Try the third example.")


# --------------------------------------------------------------------------
# Page 5: Prevention and recovery
# --------------------------------------------------------------------------
def simulation_view(title: str, plans: List[List[List[int]]], sim: alg.SimulationResult) -> None:
    st.markdown(f"**{title}**")
    st.write("Plans: " + "; ".join(
        f"{p}: " + " then ".join(alg.fmt(r) for r in plan)
        for p, plan in zip(alg.PREVENTION_PROCESSES, plans)))
    st.dataframe(pd.DataFrame(sim.log), hide_index=True)
    if sim.deadlocked:
        st.error(f"{alg.DEADLOCK_DETECTED}: {', '.join(sim.deadlocked)}")
    elif sim.rejected:
        st.warning(f"Policy rejected: {', '.join(sim.rejected)}. {alg.NO_DEADLOCK_DETECTED}. "
                   f"Completed: {', '.join(sim.completed) or 'none'}")
    else:
        st.success(f"{alg.NO_DEADLOCK_DETECTED}. All finished: {', '.join(sim.completed)}")


def prevention_tab() -> None:
    p, r, t = alg.PREVENTION_PROCESSES, alg.PREVENTION_RESOURCES, alg.PREVENTION_TOTAL
    st.subheader("A. Resource ordering (breaks circular wait)")
    st.write(f"Global order: {' < '.join(r)}. A process may only request a resource type ranked higher than "
             "every type it already holds. Resources: A and B, one instance each.")
    left, right = st.columns(2)
    with left:
        simulation_view("Original: no policy", alg.prevention_plans("unordered"),
                        alg.simulate_acquisition(p, r, t, alg.prevention_plans("unordered")))
    with right:
        simulation_view("With ordering enforced (P1 follows A then B)", alg.prevention_plans("ordered"),
                        alg.simulate_acquisition(p, r, t, alg.prevention_plans("ordered"), alg.ordering_enforcer(r)))
    with st.expander("What if P1 keeps its non-compliant plan (B then A)?"):
        simulation_view("Ordering enforced, violating plan", alg.prevention_plans("unordered"),
                        alg.simulate_acquisition(p, r, t, alg.prevention_plans("unordered"), alg.ordering_enforcer(r)))
    st.caption("Why it works: every request goes to a higher-ranked resource, so a cycle of waiting processes "
               "would need a rank to be both higher and lower than itself, which is impossible. "
               "This holds only if the rule is enforced for **every** request.")

    st.subheader("B. Eliminate hold-and-wait (request everything at once)")
    left, right = st.columns(2)
    with left:
        simulation_view("Original: incremental requests", alg.prevention_plans("incremental"),
                        alg.simulate_acquisition(p, r, t, alg.prevention_plans("incremental")))
    plans = alg.prevention_plans("all_at_once")
    with right:
        simulation_view("Modified: all at once", plans, alg.simulate_acquisition(p, r, t, plans, alg.hold_wait_enforcer(plans)))
    st.caption("Trade-offs: resources are held (idle) before they are needed, which lowers utilization; "
               "processes that need many resources may wait a long time or starve, reducing concurrency.")

    st.subheader("Try the ordering rule yourself")
    cfg: val.SystemState = st.session_state.cfg
    proc = st.selectbox("Process", cfg.process_ids, key="pol_proc")
    idx = cfg.process_ids.index(proc)
    req_text = st.text_input(f"Request ({', '.join(cfg.resource_ids)})", "0, 0, 0" if cfg.n_resources == 3 else
                             ", ".join("0" for _ in cfg.resource_ids), key="pol_req")
    vec, errs = val.parse_vector(req_text, cfg.n_resources, "Request")
    if errs:
        st.error(" ; ".join(errs))
    else:
        held = cfg.allocation[idx]
        check = alg.check_resource_ordering(held, vec, cfg.resource_ids)
        st.write(f"{proc} currently holds {alg.fmt(held)} (active configuration from page 1).")
        (st.success if check.allowed else st.error)(
            ("ALLOWED: " if check.allowed else "VIOLATION: ") + "; ".join(check.messages))


def recovery_tab() -> None:
    st.subheader("Recovery by process termination")
    examples = {k: v for k, v in alg.deadlock_examples().items() if alg.detect_deadlock(v).deadlock_detected}
    choice = st.selectbox("Deadlocked scenario", list(examples), key="rec_choice")
    if st.session_state.get("rec_loaded") != choice:
        st.session_state.rec_scn = examples[choice].copy()
        st.session_state.rec_loaded = choice
        st.session_state.rec_last = None
        st.session_state.rec_history = []
    if st.button("Reset this scenario"):
        st.session_state.rec_loaded = None
        st.rerun()

    scn: val.DetectionScenario = st.session_state.rec_scn
    det = alg.detect_deadlock(scn)
    show_detection(scn, det)
    if st.session_state.rec_history:
        st.caption("Terminated so far: " + ", ".join(st.session_state.rec_history))

    if det.deadlock_detected:
        suggestion = alg.suggest_victim(scn)
        st.info(f"Suggested victim (fewest held resources): **{suggestion}**. Choose any deadlocked process.")
        victim = st.selectbox("Process to terminate", det.deadlocked, key=f"victim_{len(st.session_state.rec_history)}")
        if st.button("Terminate process and re-run detection", type="primary"):
            rec = alg.terminate_process(scn, victim)
            st.session_state.rec_scn = rec.after
            st.session_state.rec_history.append(victim)
            st.session_state.rec_last = rec
            st.rerun()
    else:
        st.success("No deadlock remains in this scenario.")

    rec = st.session_state.get("rec_last")
    if rec is not None:
        st.divider()
        st.subheader(f"Result of terminating {rec.victim}")
        b, a = st.columns(2)
        b.markdown("**Before**")
        b.dataframe(matrix_df(rec.before.allocation, rec.before.process_ids, rec.before.resource_ids))
        b.write(f"Available: {alg.fmt(rec.before.available)}; detection: {rec.detection_before.status}")
        a.markdown("**After**")
        a.dataframe(matrix_df(rec.after.allocation, rec.after.process_ids, rec.after.resource_ids))
        a.write(f"Available: {alg.fmt(rec.after.available)}; detection: {rec.detection_after.status}")
        st.write(f"Released resources: {alg.fmt(rec.released)}")
        (st.success if rec.consistent else st.error)(
            "Consistency check: sum(Allocation) + Available = Total for every resource."
            if rec.consistent else "Inconsistent state after recovery!")
        if rec.detection_after.deadlock_detected:
            st.warning(f"Deadlock still present among {', '.join(rec.detection_after.deadlocked)}.")
        else:
            st.success(alg.NO_DEADLOCK_DETECTED + " after recovery.")
        st.warning("Side effect: " + rec.note)


def page_prevention_recovery() -> None:
    st.header("5. Deadlock Prevention and Recovery")
    tab1, tab2 = st.tabs(["Prevention", "Recovery"])
    with tab1:
        prevention_tab()
    with tab2:
        recovery_tab()


# --------------------------------------------------------------------------
# Page 6: Test cases and results
# --------------------------------------------------------------------------
def page_tests() -> None:
    st.header("6. Test Cases and Results")
    st.subheader("A. Analytical results (TC1-TC6)")
    st.caption("Each row is produced by calling the real functions in algorithms.py; 'Actual Result' is "
               "computed, and Pass/Fail compares actual values with expectations in code.")
    if st.button("Run All Tests", type="primary"):
        st.session_state.analytical = alg.run_analytical_tests()
    if st.session_state.analytical is None:
        st.info("Press **Run All Tests** to execute TC1-TC6.")
    else:
        rows, sub = st.session_state.analytical
        table = pd.DataFrame(rows)
        passed = (table["Pass / Fail"] == "PASS").sum()
        (st.success if passed == len(table) else st.error)(f"{passed} of {len(table)} analytical test cases passed")
        st.dataframe(table, hide_index=True)
        st.download_button("Download results as CSV", table.to_csv(index=False).encode("utf-8"),
                           file_name="analytical_test_results.csv", mime="text/csv")
        st.markdown("**TC6 detail: boundary and invalid inputs**")
        st.dataframe(pd.DataFrame(sub), hide_index=True)

    st.divider()
    st.subheader("B. Automated unit tests (pytest)")
    st.caption("These are the tests in test_algorithms.py. They are separate from the analytical table above "
               "and are normally run from the terminal with `python -m pytest -v`.")
    if st.button("Run pytest now"):
        folder = Path(__file__).resolve().parent
        try:
            proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
                                  cwd=folder, capture_output=True, text=True, timeout=120)
            st.session_state.pytest_output = (proc.returncode == 0, proc.stdout + proc.stderr)
        except Exception as exc:  # pytest missing, timeout, ...
            st.session_state.pytest_output = (False, f"Could not run pytest: {exc}")
    output = st.session_state.pytest_output
    if output is not None:
        (st.success if output[0] else st.error)("pytest passed" if output[0] else "pytest reported problems")
        st.code(output[1])


# --------------------------------------------------------------------------
# Page 7: About
# --------------------------------------------------------------------------
def page_about() -> None:
    st.header("7. About the Algorithms")
    st.markdown("""
**Deadlock** is a situation where a set of processes are all blocked, each waiting for a resource held by another process in the set.

**Four necessary conditions:** mutual exclusion, hold and wait, no preemption, circular wait.

| Approach | Idea | In this project |
|---|---|---|
| Prevention | Make at least one condition impossible | Resource ordering (circular wait), all-at-once requests (hold and wait) |
| Avoidance | Grant a request only if the state stays safe | Banker's Algorithm (pages 2 and 3) |
| Detection | Let deadlock happen, then find it | Detection algorithm (page 4) |
| Recovery | Break a detected deadlock | Terminate a process (page 5) |

**Banker's Algorithm.** `Need = Maximum - Allocation`. A state is *safe* if some order lets every process
finish with the resources available at its turn (a *safe sequence*). A request is granted only if
`Request <= Need`, `Request <= Available`, and the resulting state is safe.

**Unsafe is not deadlock.** Unsafe means deadlock is *possible*; processes might still finish if they never
request their full maximum. Deadlock means processes are *already* stuck.

**Why request handling and detection are separate.** Banker's works from *maximum claims* and prevents entering
risky states. Detection works from *actual outstanding requests* and finds a deadlock that already exists.

**Limitations.** Processes must declare maximum claims in advance; the number of processes and resources is
fixed; resources are reusable and single-class; the simulation is a snapshot, not a real scheduler;
requests of a terminated process are simply dropped.
""")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    init_state()
    st.title("Deadlock Analysis and Resource Allocation Dashboard")
    st.write("An educational tool for the Operating Systems course: it applies Banker's Algorithm, "
             "resource-request handling, deadlock detection, prevention and recovery to resource states "
             "you configure. Everything runs locally; no database or external service is used.")

    with st.sidebar:
        st.header("Navigation")
        page = st.radio("Go to", PAGES, label_visibility="collapsed")
        st.divider()
        cfg: val.SystemState = st.session_state.cfg
        st.markdown("**Current system**")
        st.write(f"{cfg.n_processes} processes, {cfg.n_resources} resource types")
        st.write(f"Available: {alg.fmt(cfg.available)}")
        safety = alg.check_safety(cfg)
        (st.success if safety.is_safe else st.error)(safety.status)
        st.button("Reset to example", on_click=reset_to_example)

    {PAGES[0]: page_config, PAGES[1]: page_safety, PAGES[2]: page_request, PAGES[3]: page_detection,
     PAGES[4]: page_prevention_recovery, PAGES[5]: page_tests, PAGES[6]: page_about}[page]()


main()
