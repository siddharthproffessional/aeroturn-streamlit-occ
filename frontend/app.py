from functools import partial

import streamlit as st
from client import HOSTED
from console import PAGES, render

st.set_page_config(page_title="AeroTurn · Operations Control Centre", layout="wide")
st.sidebar.title("AeroTurn")
st.sidebar.caption("Airport Operations Control Centre · Synthetic")
pages = [
    st.Page(
        partial(render, title),
        title=title,
        url_path=title.lower().replace(" & ", "-").replace(" ", "-"),
        default=i == 0,
    )
    for i, title in enumerate(PAGES)
]
selected = st.navigation(
    {"Operations": pages[:6], "Coordination": pages[6:10], "Exercise": pages[10:]}
)
with st.sidebar:
    st.text_input("OCC access token", type="password", key="access")
    if HOSTED:
        st.selectbox("Rehearsal", ["judges","practice"], key="room",
                     on_change=lambda: st.session_state.pop("last_action", None))
    auto = st.toggle("Refresh overview every 5 seconds", not HOSTED)
    st.button("Refresh now")
if HOSTED and not st.session_state.get("access"):
    st.title("AeroTurn · Airport Operations Control Centre")
    st.info("Enter the hosted OCC token in the sidebar to open the EK-812 rehearsal.")
    st.stop()
if selected.title == "OCC Overview" and auto:

    @st.fragment(run_every=5)
    def overview():
        render("OCC Overview")

    overview()
else:
    selected.run()
