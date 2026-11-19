"""Streamlit views for the synthetic OCC. Operational records come from FastAPI."""

import json
from collections import Counter
from html import escape
from uuid import uuid4

import client
import plotly.graph_objects as go
import streamlit as st

TEAL = "#53d5c6"
BLUE = "#679eff"
AMBER = "#ffbd69"
RED = "#ff878f"
COLOURS = {
    "Recommended": BLUE,
    "Validated": TEAL,
    "Staged": AMBER,
    "Approved": "#a49aff",
    "Executed": "#76dfa1",
    "Rejected": RED,
    "Rolled back": "#f4a478",
    "Unconfirmed": AMBER,
}
STYLE = """<style>
.stApp {background:#0b1423;color:#e5edf5}
[data-testid="stSidebar"] {background:#101e2e;border-right:1px solid #26374d}
[data-testid="stHeader"] {background:#0b1423eb}
.block-container {max-width:1540px;padding-top:2.8rem;padding-bottom:2rem}
h1,h2,h3 {letter-spacing:-.028em}
[data-testid="stMetric"] {padding:.75rem .9rem;background:#142236;border:1px solid #2b4056;border-radius:8px}
[data-testid="stMetricLabel"] {color:#afc2d3}
[data-testid="stMetricValue"] {font-variant-numeric:tabular-nums;font-size:1.7rem}
.flight-strip {display:flex;align-items:center;gap:.65rem;flex-wrap:wrap;background:#12263b;border:1px solid #29445e;
border-left:3px solid #53d5c6;border-radius:6px;padding:.65rem 1rem;margin:0 0 1rem;color:#c8daea}
.flight-strip strong {font:700 1.1rem monospace;color:#fff}
.occ-pill {display:inline-block;font:600 .84rem sans-serif;padding:.28rem .6rem;border-radius:5px;border:1px solid currentColor}
@media(max-width:700px){.block-container{padding:2.7rem 1rem 1rem}.flight-strip{gap:.4rem}}
</style>"""


def badge(text, colour):
    return f'<span class="occ-pill" style="color:{colour}">{escape(str(text))}</span>'


def metrics(*pairs):
    for col, (label, value) in zip(st.columns(len(pairs)), pairs):
        col.metric(label, value if value is not None else "Unavailable")


def table(rows, empty="No records in this view."):
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.caption(empty)


def chart(fig, height=250, stacked=False):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#101e2e",
        plot_bgcolor="#101e2e",
        colorway=[TEAL, BLUE, AMBER],
        font=dict(color="#c8daea"),
        height=height,
        margin=dict(l=14, r=14, t=12, b=8),
        legend=dict(orientation="h", y=-0.2),
        barmode="stack" if stacked else "group",
    )
    fig.update_yaxes(gridcolor="#24384b", rangemode="tozero")
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})


def seats(s):
    fig = go.Figure()
    flights = s["alternatives"]
    for name, col, vals in [
        ("General", BLUE, [a["available"] - a["reserved"] for a in flights]),
        ("Priority protected", TEAL, [a["reserved"] for a in flights]),
    ]:
        fig.add_bar(name=name, x=[a["id"] for a in flights], y=vals, marker_color=col)
    chart(fig, stacked=True)


def holds(s):
    if s["safety_holds"]:
        for hold in s["safety_holds"]:
            st.warning(hold["reason"])
    else:
        st.success("Dispatch guards cleared")


def delay_button(s):
    delay = s["exercise"].get("delay_minutes")
    if delay is not None:
        client.action(
            f"Trigger {delay}-minute delay",
            "/simulation/delay",
            disabled=s["flight"]["delay"] == delay,
        )


def overview(s):
    f = s["flight"]
    delay = s["exercise"].get("delay_minutes")
    cohort = s["exercise"].get("risk_records")
    st.caption(
        f"Disruption exercise · {delay} min arrival delay · {cohort} connection-risk records"
        if delay is not None
        else "Exercise profile unavailable"
    )
    metrics(
        ("Arrival delay", f"{f['delay']} min"),
        ("Connecting passengers", s["passengers"]),
        ("Currently at risk", s["risk"]),
        ("Priority at risk", s["protected"]),
    )
    left, right = st.columns([1.2, 1])
    with left:
        st.subheader("Passenger recovery")
        st.progress(
            min(1.0, s["recovered"] / cohort) if cohort else 0.0,
            text=f"{s['recovered']} recovered of {cohort if cohort is not None else 'unknown'} risk records",
        )
        st.caption("Available replacement seats by flight")
        seats(s)
    with right:
        st.subheader("Dispatch and approvals")
        c = s["crew"]
        metrics(
            ("Duty remaining", minutes(c["remaining"])),
            (
                "Pending approvals",
                sum(p["status"] == "pending" for p in s["proposals"]),
            ),
        )
        st.write("Hydraulic inspection")
        st.markdown(
            badge(
                "Maintenance clear" if s["maintenance_clear"] else "Clearance held",
                TEAL if s["maintenance_clear"] else AMBER,
            ),
            unsafe_allow_html=True,
        )
        holds(s)
        if c["projected"] is not None and c["duty_limit"] is not None:
            st.caption(
                f"Projected duty margin including the exercise buffer: {c['duty_limit'] - c['projected']:+d} min"
            )
    delay_button(s)


def minutes(value):
    return "Unavailable" if value is None else f"{value} min"


def flights(s):
    rows = client.fetch("/api/flights")
    f = s["flight"]
    metrics(
        ("Gate", f["gate"]),
        ("Arrival delay", minutes(f["delay"])),
        ("Turnaround departure", f"T{f['departure']:+d}"),
    )
    st.subheader("Movement schedule")
    st.caption("Schedule minutes are relative to the planned arrival.")
    selected = st.multiselect("Leg type", sorted({row["kind"] for row in rows}))
    table([r for r in rows if not selected or r["kind"] in selected])


def latest_plan(s):
    for entry in s["activity"]:
        report = json.loads(entry["report"])
        if (
            report.get("schema_version") == 2
            and report.get("proposed_assignments")
            and report.get("purpose") != "final report"
        ):
            return entry["id"], report
    return None, None


def recovery_controls(s):
    rid, plan = latest_plan(s)
    if not plan:
        st.caption("Generate a recovery analysis to review and execute a batch.")
        return
    items = plan["proposed_assignments"]
    st.markdown(badge("Recommended", BLUE), unsafe_allow_html=True)
    with st.expander(f"Analysis #{rid} · {len(items)} proposed assignments"):
        table(items)
    client.action(
        "Execute recovery batch",
        "/api/recovery/execute",
        {"analysis_id": rid},
        disabled=not s["risk"],
    )
    key = st.session_state.setdefault("conflict_key", uuid4().hex)
    client.action(
        "Simulate transaction rollback",
        "/api/recovery/simulate-failure",
        {
            "assignments": items,
            "idempotency_key": "occ-sim-" + key + "-" + str(rid),
            "inject_conflict_after": min(3, len(items)),
        },
        disabled=not s["risk"],
    )


def passengers(s):
    metrics(
        ("Unresolved connections", s["risk"]),
        ("Priority at risk", s["protected"]),
        ("Recovered", s["recovered"]),
    )
    st.subheader("Connection manifest")
    people = client.fetch("/api/passengers")
    view = st.radio(
        "Manifest view",
        ["At risk", "Priority at risk", "All passengers"],
        horizontal=True,
    )
    query = st.text_input("Find passenger, booking or destination").strip().lower()
    table(
        [
            p
            for p in people
            if (view == "All passengers" or p["at_risk"])
            and (view != "Priority at risk" or p["category"] != "standard")
            and any(
                query in p[k].lower()
                for k in ("id", "booking_reference", "destination")
            )
        ]
    )
    unresolved = [p for p in people if p["at_risk"]]
    if unresolved:
        with st.expander("Recover an individual passenger"):
            person = st.selectbox(
                "Passenger",
                unresolved,
                format_func=lambda p: (
                    f"{p['id']} · {p['destination']} · {p['category']}"
                ),
            )
            routes = [
                a
                for a in s["alternatives"]
                if a["destination"] == person["destination"] and a["available"] > 0
            ]
            if routes:
                route = st.selectbox(
                    "Replacement flight",
                    routes,
                    format_func=lambda a: f"{a['id']} · {a['available']} open seats",
                )
                key = st.session_state.setdefault("manual_booking_key", uuid4().hex)
                client.action(
                    "Rebook passenger",
                    "/api/recovery/execute",
                    {
                        "idempotency_key": f"{key}-{person['id']}-{route['id']}",
                        "assignments": [
                            {"passenger": person["id"], "alternative": route["id"]}
                        ],
                    },
                )
            else:
                st.caption("No replacement seats to this destination.")
    recovery_controls(s)


def baggage(s):
    rows = client.fetch("/bags")
    metrics(
        ("Checked bags", s["bags"]["total"]),
        ("Rerouted", s["bags"]["transferred"]),
        ("Passengers with bags", len({b["passenger"] for b in rows})),
    )
    st.subheader("Bags by current routing")
    counts = Counter(r["itinerary"] for r in rows)
    chart(go.Figure(go.Bar(x=list(counts), y=list(counts.values()), marker_color=TEAL)))
    query = st.text_input("Find bag tag, passenger or flight").upper().strip()
    table([r for r in rows if any(query in str(v).upper() for v in r.values())])


def crew(s):
    c = s["crew"]
    metrics(
        ("Assigned team", c["id"]),
        ("Duty remaining", minutes(c["remaining"])),
        ("Projected duty", minutes(c["projected"])),
    )
    st.subheader("Duty clearance")
    st.caption(
        f"Synthetic duty scheme {s['duty_profile']} · configured cap {minutes(c['duty_limit'])}"
    )
    st.markdown(
        badge(
            "Validated" if c["legal"] else "Duty hold", TEAL if c["legal"] else AMBER
        ),
        unsafe_allow_html=True,
    )
    for h in s["safety_holds"]:
        if h["violated_rule"].startswith("crew."):
            st.write(h["reason"])
    client.action("Validate assigned crew", "/api/crew/validate")
    client.action("Assign relief crew", "/crew/relief", disabled=c["id"] == "Relief")


def maintenance(s):
    st.markdown(
        badge(
            "Validated" if s["maintenance_clear"] else "Maintenance hold",
            TEAL if s["maintenance_clear"] else AMBER,
        ),
        unsafe_allow_html=True,
    )
    st.subheader("Inspection and release records")
    table(s["inspections"])
    client.action("Validate maintenance clearance", "/api/maintenance/validate")
    expired = {
        hold["record_ids"].get("inspection")
        for hold in s["safety_holds"]
        if hold["violated_rule"] == "maintenance.expired"
    }
    pending = [i for i in s["inspections"] if not i["release_id"] or i["id"] in expired]
    if pending:
        i = st.selectbox(
            "Inspection to release",
            pending,
            format_func=lambda i: f"#{i['id']} · {i['item']}",
        )
        token = st.text_input("Authorised maintenance token", type="password")
        client.action(
            "Sign inspection",
            f"/maintenance/inspections/{i['id']}/sign",
            token=token,
            disabled=not token,
        )


def analysis(s):
    provider = st.selectbox(
        "Analysis provider", ["offline"] if client.HOSTED else ["configured", "ollama", "gemini", "groq", "offline"]
    )
    body = {} if provider == "configured" else {"provider": provider}
    gate = st.selectbox(
        "Gate change to assess",
        [None] + [g for g in s["gates"] if g != s["flight"]["gate"]],
        format_func=lambda g: g or "None",
    )
    if gate:
        body["change"] = {"kind": "gate", "value": gate}
    client.action("Run recovery analysis", "/api/recovery/analyse", body)
    return body


def agent(s):
    analysis(s)
    for row in s["activity"]:
        report = json.loads(row["report"])
        with st.expander(
            f"#{row['id']} · {report.get('purpose', 'Analysis')} · {row['provider']} · {row['at']}",
            expanded=row == s["activity"][0],
        ):
            st.write(report.get("executive_report", ""))
            table(report.get("action_sequence", []), "No proposed sequence.")
            st.json(report, expanded=False)
            if report.get("proposed_schedule_change"):
                client.action(
                    f"Stage change from analysis #{row['id']}",
                    f"/agent/actions/{row['id']}/stage",
                )
    recovery_controls(s)


def approval(s):
    pending = [p for p in s["proposals"] if p["status"] == "pending"]
    kind = st.radio("Proposed change", ["Gate", "Departure"], horizontal=True)
    if kind == "Gate":
        value = st.selectbox(
            "New gate", [g for g in s["gates"] if g != s["flight"]["gate"]]
        )
    else:
        value = str(
            st.number_input(
                "New departure (scenario minute)",
                min_value=0,
                value=s["flight"]["departure"],
            )
        )
    client.action(
        "Stage for controller approval",
        "/api/schedule/stage",
        {"kind": kind.lower(), "value": value},
        disabled=not value,
    )
    st.subheader("Decision queue")
    table(
        [
            {
                **p,
                "status": {
                    "pending": "Staged",
                    "approved": "Approved",
                    "rejected": "Rejected",
                }.get(p["status"], p["status"]),
            }
            for p in s["proposals"]
        ],
        "No proposals staged.",
    )
    if pending:
        p = st.selectbox(
            "Review staged proposal",
            pending,
            format_func=lambda p: f"#{p['id']} · {p['kind']} → {p['value']}",
        )
        token = st.text_input("Controller token", type="password")
        reason = st.text_input("Reason for rejection (optional)", max_chars=500)
        left, right = st.columns(2)
        with left:
            client.action(
                "Approve change",
                f"/api/approvals/{p['id']}/approve",
                token=token,
                disabled=not token,
            )
        with right:
            client.action(
                "Reject change",
                f"/api/approvals/{p['id']}/reject",
                {"reason": reason.strip() or None},
                token,
                disabled=not token,
            )


def history(path):
    before = st.number_input("Before audit ID (0 for newest)", min_value=0, value=0)
    return client.fetch(
        path + "?limit=100" + (f"&before_id={before}" if before else "")
    )


def transactions(s):
    rows = history("/api/transactions")
    for row in rows:
        detail = row["detail"]
        status = (
            "Executed"
            if row["status"] == "committed"
            else (
                "Rolled back"
                if detail.get("verified") is True
                else "Rollback unverified"
            )
        )
        with st.expander(
            f"#{row['audit_id']} · {status} · {row['at']}", expanded=row == rows[0]
        ):
            st.markdown(
                badge(status, COLOURS.get(status, AMBER)), unsafe_allow_html=True
            )
            st.json(detail)
    if not rows:
        st.caption("No recovery attempts recorded in this window.")


def audit(s):
    client.action("Generate recovery report", "/agent/report")
    for entry in s["activity"]:
        report = json.loads(entry["report"])
        if report.get("purpose") == "final report":
            st.write(report["executive_report"])
            st.download_button(
                "Download recovery report",
                json.dumps(report, indent=2),
                "recovery-report.json",
                "application/json",
            )
            break
    st.subheader("Audit trail")
    rows = history("/api/audit")
    table(rows)
    st.download_button(
        "Export audit window",
        json.dumps(rows, indent=2),
        "occ-audit.json",
        "application/json",
    )


def simulation(s):
    delay_button(s)
    analysis(s)
    recovery_controls(s)
    st.subheader("Dispatch checks")
    client.action("Check dispatch clearance", "/simulation/dispatch-check")
    holds(s)


PAGES = {
    "OCC Overview": overview,
    "Flight Operations": flights,
    "Passenger Recovery": passengers,
    "Baggage Intelligence": baggage,
    "Crew & Duty Monitoring": crew,
    "Maintenance Control": maintenance,
    "Recovery Agent": agent,
    "Controller Approval": approval,
    "Transaction Monitor": transactions,
    "Audit & Reports": audit,
    "Demo Simulation": simulation,
}


def render(title):
    st.markdown(STYLE, unsafe_allow_html=True)
    st.title(title)
    s = client.fetch("/state")
    f = s["flight"]
    flag = badge(
        "Dispatch clear" if s["dispatch_ready"] else "Dispatch held",
        TEAL if s["dispatch_ready"] else AMBER,
    )
    st.markdown(
        f'<div class="flight-strip"><strong>{escape(f["id"])}</strong> <span>Gate {escape(f["gate"])}</span> {flag}</div>',
        unsafe_allow_html=True,
    )
    if "last_action" in st.session_state:
        status, label, data = st.session_state["last_action"]
        with st.expander(f"Last response · {label} · {status}"):
            st.markdown(
                badge(status, COLOURS.get(status, TEAL)), unsafe_allow_html=True
            )
            st.json(data)
    PAGES[title](s)
