"""Streamlit entry point: the navigation shell over Cleat's five pages."""

import streamlit as st

st.set_page_config(page_title="Cleat", page_icon=":material/shield:", layout="wide")

try:
    from cleat import settings  # importing enforces the sandbox-only guard (invariant I-6)
except Exception as error:  # the guard's own message says exactly what to fix
    st.error(f"Cleat refused to start: {error}", icon=":material/error:")
    st.stop()

from cleat.firewall.compiler import seed_default_policy  # noqa: E402  imported after the guard
from cleat.ui.theme import LOGO_SVG  # noqa: E402


@st.cache_resource
def prepare_storage() -> None:
    """Create the tables and save the bundled default policy, once per server process."""
    seed_default_policy()


prepare_storage()
st.logo(LOGO_SVG)

navigation = st.navigation(
    [
        st.Page("views/overview.py", title="Overview", icon=":material/dashboard:"),
        st.Page("views/inbox.py", title="Inbox", icon=":material/inbox:"),
        st.Page("views/approvals.py", title="Approvals", icon=":material/rule:"),
        st.Page("views/audit_log.py", title="Audit Log", icon=":material/history:"),
        st.Page("views/policies.py", title="Policies", icon=":material/policy:"),
    ]
)
st.sidebar.caption(f"{settings.APP_NAME}: a spending firewall for AI support agents that touch PayPal.")
st.sidebar.caption("Try it: Inbox → scenario 03, 05, 07, then 04 + Approve.")
navigation.run()
