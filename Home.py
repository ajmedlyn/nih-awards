import streamlit as st

st.title("NIH Funding Dashboard")
st.markdown("""
This dashboard tracks NIH funding trends from 2001 to present, analyzing the impact of recent budget changes on American scientific research.

**Use the sidebar to navigate between sections:**

- **Funding Cliff** — 25-year arc of NIH obligations, nominal vs. inflation-adjusted
- **Pipeline** — New awards vs. non-competing continuations over time
- **NIH Institutes** — Which NIH institutes absorbed the largest funding losses
- **Universities and Research Institutes** — Top research institutions by dollar decline

*Data source: NIH RePORTER API. Last updated May 2026.*
""")
