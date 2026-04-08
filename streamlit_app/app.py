import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

st.set_page_config(
    page_title="Corpus Christi Civic Data",
    page_icon="🏛️",
    layout="wide",
)

st.sidebar.title("🏛️ CC Civic Data")
st.sidebar.markdown("Corpus Christi city council meeting records.")
st.sidebar.divider()

pg = st.navigation([
    st.Page("pages/meetings.py",     title="Meetings",      icon="📅"),
    st.Page("pages/persons.py",      title="Persons",       icon="👤"),
    st.Page("pages/transparency.py", title="Transparency",  icon="🔍"),
    st.Page("pages/map_speakers.py", title="Map Speakers",  icon="🔒"),
])
pg.run()
