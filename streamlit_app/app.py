import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

st.set_page_config(
    page_title="Corpus Christi Civic Data",
    page_icon="🏛️",
    layout="wide",
)

pg = st.navigation([
    st.Page("pages/persons.py", title="Persons", icon="👤"),
    st.Page("pages/meetings.py", title="Meetings", icon="📋"),
])
pg.run()
