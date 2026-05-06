import streamlit as st
import duckdb
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import date

today = date.today()
st.header("Research Institution Funding Loss")
st.caption("Comparing FY2024 vs FY2025 funding by research institution. "
           "Top 20 by dollar loss, among institutions with at least $25M in FY2024 NIH funding.")

con = duckdb.connect("nih_awards_slim.duckdb")
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

# Filter out obvious corporate/non-research entities
corporate_patterns = r',?\s*(Inc\.?|LLC|L\.L\.C|Corp\.?|Corporation|Holdings|Co\.)(\s|$)'
compare = compare[~compare.index.str.contains(corporate_patterns, case=False, regex=True, na=False)]

compare["pct_change"] = (compare["FY2025"] - compare["FY2024"]) / compare["FY2024"] * 100
compare["dollar_loss"] = compare["FY2025"] - compare["FY2024"]
compare = compare.nsmallest(20, "dollar_loss").reset_index()
compare["pct_change"] = compare["pct_change"].round(1)

# Title-case + truncate long names for display; keep full name in hover
def _shorten(name: str, limit: int = 32) -> str:
    pretty = name.title().replace(" At ", " at ").replace(" Of ", " of ").replace(" The ", " the ")
    return pretty if len(pretty) <= limit else pretty[: limit - 1] + "…"

compare["display_name"] = compare["InstitutionName"].apply(_shorten)

n_rows = len(compare)
chart_height = max(500, 36 * n_rows + 100)
sorted_names = list(compare["display_name"])

fig = px.scatter(
    compare,
    x="pct_change",
    y="display_name",
    title="University & Research Institute Funding: FY2024 vs FY2025",
    labels={"pct_change": "% Change", "display_name": "Institution"},
    color="pct_change",
    color_continuous_scale="RdYlGn",
    range_color=[-30, 5],
    custom_data=["InstitutionName", "FY2024", "FY2025", "dollar_loss"]
)

fig.update_traces(
    marker=dict(size=9),
    hovertemplate=(
        "<b>%{customdata[0]}</b><br>"
        "%{x:.1f}% change<br>"
        "FY2024: $%{customdata[1]:.2f}B<br>"
        "FY2025: $%{customdata[2]:.2f}B<br>"
        "Dollar loss: $%{customdata[3]:.2f}B<extra></extra>"
    )
)

# Alternating row backgrounds
for i in range(n_rows):
    if i % 2 == 0:
        fig.add_shape(
            type="rect",
            xref="paper", x0=0, x1=1,
            yref="y", y0=i - 0.5, y1=i + 0.5,
            fillcolor="rgba(0,0,0,0.04)",
            line_width=0,
            layer="below"
        )

# Lollipop lines
for _, row in compare.iterrows():
    fig.add_shape(
        type="line",
        x0=0, x1=row["pct_change"],
        y0=row["display_name"], y1=row["display_name"],
        line=dict(color="gray", width=1.5)
    )

fig.add_vline(x=0, line_dash="dash", line_color="gray", line_width=1)

fig.update_layout(
    height=chart_height,
    plot_bgcolor="white",
    coloraxis_showscale=False,
    xaxis=dict(ticksuffix="%", tickformat=".1f", showgrid=True, gridcolor="rgba(0,0,0,0.06)"),
    yaxis=dict(
        showgrid=False,
        automargin=False,
        categoryorder="array",
        categoryarray=sorted_names,
        tickmode="linear",
        tickfont=dict(size=11)
    ),
    margin=dict(l=240, r=40, t=60, b=60)
)

st.plotly_chart(fig, use_container_width=True)
