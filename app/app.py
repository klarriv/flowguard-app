"""
app.py — Main entry point for the FlowGuard app.
Run with:  streamlit run app/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

st.set_page_config(
    page_title="FlowGuard",
    page_icon="F",
    layout="wide",
    initial_sidebar_state="expanded",
)

with st.sidebar:
    logo_path = Path(__file__).parent / "assets" / "logo_capt-air.jpg"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    st.markdown("---")
    st.markdown("### Calculations")
    st.page_link("app.py", label="Home")
    st.page_link("pages/1_Dust_Vent_NFPA68.py", label="💨 Dust Vent — NFPA 68 Ch.8")
    st.markdown("---")
    st.caption("NFPA 68 (2023) · Internal use only")

st.title("Engineering Calculations")
st.markdown("Select a calculation from the sidebar to begin.")

st.markdown("---")
st.markdown("#### Available calculations")
st.page_link("pages/1_Dust_Vent_NFPA68.py", label="💨 Dust Deflagration Vent Sizing — NFPA 68 (2023) Ch.8")
