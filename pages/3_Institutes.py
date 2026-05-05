import streamlit as st
import duckdb
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import date

today = date.today()
st.header("NIH Institute Funding Changes")
st.caption("Comparing FY2024 vs FY2025 funding by institute. Sorted by proportional loss.")

con = duckdb.connect("nih_awards_slim.duckdb")
df = con.execute("""
SELECT
    fiscal_year,
    agency_ic_admin_abbrev AS ic,
    strftime(award_notice_date::TIMESTAMP, '%Y-%m') AS month,
    COUNT(*) AS n_awards,
    SUM(award_amount) AS monthly_funding,
    SUM(SUM(award_amount)) OVER (
        PARTITION BY fiscal_year, agency_ic_admin_abbrev
        ORDER BY strftime(award_notice_date::TIMESTAMP, '%Y-%m')
    ) AS running_total
FROM nih_awards_national
WHERE award_notice_date IS NOT NULL
    AND agency_code = 'NIH'
    AND fiscal_year BETWEEN 2020 AND 2026
GROUP BY fiscal_year, agency_ic_admin_abbrev, month
ORDER BY fiscal_year, agency_ic_admin_abbrev, month;
""").df()

annual = (
    df.groupby(["fiscal_year", "ic"], as_index=False)["monthly_funding"]
      .sum()
      .rename(columns={"monthly_funding": "total_dollars"})
)

fy2024 = annual[annual["fiscal_year"] == 2024].set_index("ic")["total_dollars"]
fy2025 = annual[annual["fiscal_year"] == 2025].set_index("ic")["total_dollars"]

compare = pd.DataFrame({"FY2024": fy2024, "FY2025": fy2025}).dropna()
compare["pct_change"] = (compare["FY2025"] - compare["FY2024"]) / compare["FY2024"] * 100
compare = compare.nsmallest(15, "pct_change").reset_index()
compare = compare.sort_values("pct_change")

compare["pct_change"] = compare["pct_change"].round(3)
fig = px.scatter(
    compare,
    x="pct_change",
    y="ic",
    title="NIH Institute Funding Change: FY2024 vs FY2025",
    labels={"pct_change": "% Change", "ic": "Institute"},
    color="pct_change",
    color_continuous_scale="RdYlGn",
    range_color=[-30, 5]
)

for _, row in compare.iterrows():
    fig.add_shape(
        type="line",
        x0=0,
        x1=row["pct_change"],
        y0=row["ic"],
        y1=row["ic"],
        line=dict(color="gray", width=1.5)
    )

fig.add_vline(x=0, line_dash="dash", line_color="gray", line_width=1)

fig.update_layout(
    plot_bgcolor="white",
    coloraxis_showscale=False,
    xaxis=dict(ticksuffix="%", tickformat=".3f", showgrid=True, gridcolor="rgba(0,0,0,0.06)"),
    yaxis=dict(showgrid=False)
)

st.plotly_chart(fig, use_container_width=True)
