import streamlit as st
import duckdb
import pandas as pd
import plotly.graph_objects as go
from datetime import date
today = date.today()
st.title("NIH Funding Dashboard")

con = duckdb.connect("/Users/andrewmedlyn/Projects/nih-awards/nih_awards_slim.duckdb")
df = con.execute("""
    SELECT fiscal_year, SUM(award_amount) / 1e9 AS obligations_billions
    FROM nih_awards_national
    WHERE fiscal_year BETWEEN 2001 AND 2026
    AND agency_code = 'NIH'
    GROUP BY fiscal_year
    ORDER BY fiscal_year
""").df()

# CPI-U annual averages (BLS CUUR0000SA0), base year = 2024
cpi = {
    2001: 177.1, 2002: 179.9, 2003: 184.0, 2004: 188.9, 2005: 195.3,
    2006: 201.6, 2007: 207.3, 2008: 215.3, 2009: 214.5, 2010: 218.1,
    2011: 224.9, 2012: 229.6, 2013: 233.0, 2014: 236.7, 2015: 237.0,
    2016: 240.0, 2017: 245.1, 2018: 251.1, 2019: 255.7, 2020: 258.8,
    2021: 270.97, 2022: 292.66, 2023: 304.70, 2024: 314.18, 2025: 320.0, 2026:326.0
}

base_cpi = cpi[2024]
df["cpi"] = df["fiscal_year"].map(cpi)
df["obligations_real"] = df["obligations_billions"] * (base_cpi / df["cpi"])

# Compute equivalent years
val_2025 = df.loc[df["fiscal_year"] == 2025, "obligations_billions"].values[0]
val_2025_real = df.loc[df["fiscal_year"] == 2025, "obligations_real"].values[0]
prior = df[df["fiscal_year"] < 2025]
idx = (prior["obligations_billions"] - val_2025).abs().idxmin()
equiv_year = df.loc[idx, "fiscal_year"]
idx_real = (prior["obligations_real"] - val_2025_real).abs().idxmin()
real_equiv_year = df.loc[idx_real, "fiscal_year"]

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=df["fiscal_year"],
    y=df["obligations_billions"],
    fill="tozeroy",
    fillcolor="rgba(99, 110, 250, 0.2)",
    line=dict(color="rgba(99, 110, 250, 0.8)", width=2),
    name="Nominal"
))

fig.add_trace(go.Scatter(
    x=df["fiscal_year"],
    y=df["obligations_real"],
    line=dict(color="crimson", dash="dash", width=1.5),
    name="Real (2024 $)"
))

events = [
    (2009, "ARRA", "green"),
    (2013, "Sequester", "orange"),
    (2020, "COVID", "steelblue"),
    (2025, "DOGE Cuts", "red"),
]

shapes = []
annotations = []
for year, label, color in events:
    shapes.append(dict(
        type="line", x0=year, x1=year, y0=0, y1=0.82,
        yref="paper", line=dict(color=color, dash="dash", width=1.5)
    ))
    annotations.append(dict(
        x=year, y=0.85, yref="paper",
        text=label, showarrow=False,
        font=dict(size=11, color=color),
        xanchor="center"
    ))

##the prior fiscal year (needed for annotation below)
latest_year = int(df["fiscal_year"].max()) - 1

# Real dollar equivalence note in top-left corner
annotations.append(dict(
    x=0.01, y=0.99, xref="paper", yref="paper",
    text=f"FY{latest_year} purchasing power ≈ FY{real_equiv_year} in real dollars",
    showarrow=False, xanchor="left", yanchor="top",
    font=dict(size=11, color="gray"),
    bgcolor="white", borderpad=4
))

fig.update_layout(
    title=dict(text="NIH Funding Obligations, FY2001–2025", font=dict(size=18)),
    xaxis_title="Federal Fiscal Year",
    yaxis_title="Awarded Total Dollars (Billions)",
    shapes=shapes,
    annotations=annotations,
    plot_bgcolor="white",
    paper_bgcolor="white",
    legend=dict(x=0.01, y=0.6, xanchor="left"),
    margin=dict(t=80, b=60, l=70, r=40),
    xaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.06)"),
    yaxis=dict(showgrid=True, gridcolor="rgba(0,0,0,0.06)"),
)
# the peak!
peak_row = df.loc[df["obligations_billions"].idxmax()]
peak_year = int(peak_row["fiscal_year"])
peak_val = peak_row["obligations_billions"]

##the prior fiscal year
latest_year = int(df["fiscal_year"].max()) - 1
latest_val = df.loc[df["fiscal_year"] == latest_year, "obligations_billions"].values[0]

ytd_year = int(df["fiscal_year"].max())
ytd_val = df.loc[df["fiscal_year"] == ytd_year, "obligations_billions"].values[0]

val_prior = df.loc[df["fiscal_year"] == latest_year - 1, "obligations_billions"].values[0]
yoy_change = (latest_val - val_prior) / val_prior * 100
today_str = today.strftime("%Y-%m-%d")
sply = con.execute("""
    SELECT fiscal_year, SUM(award_amount) / 1e9 AS obligations_billions
    FROM nih_awards_national
    WHERE fiscal_year IN (2025, 2026)
    AND agency_code = 'NIH'
    AND CAST(award_notice_date AS DATE) <= ?
    GROUP BY fiscal_year
""", [today_str]).df()
print(sply)
col1, col2, col3, col4 = st.columns(4)
col1.metric("Peak Funding", f"${peak_val:.1f}B", f"FY{peak_year}")
col2.metric("Prior Fiscal Year", f"${latest_val:.1f}B", f"{yoy_change:.1f}%")
col3.metric("Current Fiscal Year To-Date", f"${ytd_val:.1f}B", f"FY{ytd_year}", delta_color="off", delta_arrow="off")

st.plotly_chart(fig, use_container_width=True)