import streamlit as st
import duckdb
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import date

today = date.today()
st.header("NIH Institute Funding Changes")
st.caption("Comparing FY2024 vs FY2025 funding by NIH institute. Sorted by proportional loss. Hover over a dot to see the full institute name.")

con = duckdb.connect("nih_awards_slim.duckdb")

# Lookup: abbreviation → full name
ic_lookup = con.execute("""
    SELECT DISTINCT agency_ic_admin_abbrev AS ic, agency_ic_admin_name AS ic_name
    FROM nih_awards_national
    WHERE agency_ic_admin_abbrev IS NOT NULL AND agency_ic_admin_name IS NOT NULL
""").df()
ic_name_map = dict(zip(ic_lookup["ic"], ic_lookup["ic_name"]))

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
compare = compare.sort_values("pct_change").reset_index(drop=True)
compare["pct_change"] = compare["pct_change"].round(1)
compare["ic_name"] = compare["ic"].map(ic_name_map).fillna(compare["ic"])
compare["dollar_loss"] = compare["FY2025"] - compare["FY2024"]

n_rows = len(compare)
chart_height = max(400, 42 * n_rows + 80)
sorted_ics = list(compare["ic"])

fig = px.scatter(
    compare,
    x="pct_change",
    y="ic",
    title="NIH Institute Funding Change: FY2024 vs FY2025",
    labels={"pct_change": "% Change", "ic": "Institute"},
    color="pct_change",
    color_continuous_scale="RdYlGn",
    range_color=[-30, 5],
    custom_data=["ic_name", "FY2024", "FY2025", "dollar_loss"]
)

fig.update_traces(
    marker=dict(size=9),
    hovertemplate=(
        "<b>%{y} — %{customdata[0]}</b><br>"
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

for _, row in compare.iterrows():
    fig.add_shape(
        type="line",
        x0=0, x1=row["pct_change"],
        y0=row["ic"], y1=row["ic"],
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
        automargin=True,
        categoryorder="array",
        categoryarray=sorted_ics,
        tickmode="linear"
    ),
    margin=dict(l=80, r=40, t=60, b=60)
)

st.plotly_chart(fig, use_container_width=True)

# Institute name reference
with st.expander("What do these abbreviations stand for?"):
    ref_df = (
        compare[["ic", "ic_name"]]
        .rename(columns={"ic": "Abbreviation", "ic_name": "Full Name"})
        .reset_index(drop=True)
    )
    st.dataframe(ref_df, hide_index=True, use_container_width=True)
    st.caption("NIH institutes and centers are the individual divisions of the National Institutes of Health. "
               "Each focuses on a specific disease area or research mission and receives its own Congressional appropriation.")
