import streamlit as st
import duckdb
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import date

today = date.today()
st.header("Research Institution Funding Loss")
st.caption("Comparing FY2024 vs FY2025 funding by Research Institutes who had at least $25 million in NIH funding in FY2024. " \
"Sorted by proportional loss.")

con = duckdb.connect("/Users/andrewmedlyn/Projects/nih-awards/nih_awards_slim.duckdb")
df = con.execute("""
SELECT
    fiscal_year,
    org_name as InstitutionName,
    strftime(award_notice_date::TIMESTAMP, '%Y-%m') AS month,
    COUNT(*) AS n_awards,
    SUM(award_amount) AS monthly_funding,
    SUM(SUM(award_amount)) OVER (
        PARTITION BY fiscal_year, org_name
        ORDER BY strftime(award_notice_date::TIMESTAMP, '%Y-%m')
    ) AS running_total
FROM main.nih_awards_national
WHERE award_notice_date IS NOT NULL
    AND agency_code = 'NIH'
    AND fiscal_year BETWEEN 2020 AND 2026
GROUP BY fiscal_year, org_name, month
ORDER BY fiscal_year, org_name, month;
""").df()

annual = (
    df.groupby(["fiscal_year", "InstitutionName"], as_index=False)["monthly_funding"]
      .sum()
      .rename(columns={"monthly_funding": "total_dollars"})
)

fy2024 = annual[annual["fiscal_year"] == 2024].set_index("InstitutionName")["total_dollars"]
fy2025 = annual[annual["fiscal_year"] == 2025].set_index("InstitutionName")["total_dollars"]

compare = pd.DataFrame({"FY2024": fy2024, "FY2025": fy2025}).dropna()
compare = compare[compare["FY2024"] >= 0.025]
compare["pct_change"] = (compare["FY2025"] - compare["FY2024"]) / compare["FY2024"] * 100
compare["dollar_loss"] = compare["FY2025"] - compare["FY2024"]
compare = compare.nsmallest(20, "dollar_loss").reset_index()

compare["pct_change"] = compare["pct_change"].round(3)
fig = px.scatter(
    compare,
    x="pct_change",
    y="InstitutionName",
    title="University Funding: FY2024 vs FY2025",
    labels={"pct_change": "% Change", "InstitutionName": "University"},
    color="pct_change",
    color_continuous_scale="RdYlGn",
    range_color=[-30, 5]
)

for _, row in compare.iterrows():
    fig.add_shape(
        type="line",
        x0=0,
        x1=row["pct_change"],
        y0=row["InstitutionName"],
        y1=row["InstitutionName"],
        line=dict(color="gray", width=1.5)
    )

fig.add_vline(x=0, line_dash="dash", line_color="gray", line_width=1)

fig.update_layout(
    plot_bgcolor="white",
    coloraxis_showscale=False,
    xaxis=dict(ticksuffix="%", tickformat=".1f", showgrid=True, gridcolor="rgba(0,0,0,0.06)"),
    yaxis=dict(showgrid=False)
)

st.plotly_chart(fig, use_container_width=True)
