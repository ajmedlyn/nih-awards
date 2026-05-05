import streamlit as st
import duckdb
import pandas as pd
import plotly.graph_objects as go
from datetime import date
today = date.today()
st.header("New vs Non-Competing Continuations")
st.caption("Comparing new award activity vs. non-competing continuations, FY2014–2025." \
"Matrix shows same-period comparison: FY2024 vs. FY2026 YTD."
"Note the steep drop in New Awards compared to a baseline of FY2024 - the last full year before the new administration.")
#context drop in the matrix. 

con = duckdb.connect("nih_awards_slim.duckdb")
df = con.execute("""
 SELECT 
    fiscal_year, 
    award_type,
	award_notice_date,
    COUNT(*) as grant_count,
    SUM(award_amount) / 1e9 as total_dollars
FROM main.nih_awards_national
WHERE award_type IN ('1','5','2')
	AND agency_code = 'NIH'
	AND fiscal_year IN (2024, 2026)
GROUP BY fiscal_year, award_type, award_notice_date
ORDER BY fiscal_year desc, award_type, award_notice_date;
""").df()
cutoff_date = pd.to_datetime(df[df["fiscal_year"] == 2026]["award_notice_date"].max())
cutoff_2024 = pd.Timestamp(year=2024, month=cutoff_date.month, day=cutoff_date.day)

filtered = df[
    ((df["fiscal_year"] == 2026) & (pd.to_datetime(df["award_notice_date"]) <= cutoff_date)) |
    ((df["fiscal_year"] == 2024) & (pd.to_datetime(df["award_notice_date"]) <= cutoff_2024))
]
type_labels = {"1": "New", "2": "Renewal", "5": "Continuation"}
filtered["award_type"] = filtered["award_type"].map(type_labels)

matrix = filtered.pivot_table(
    index="fiscal_year",
    columns="award_type",
    values="total_dollars",
    aggfunc="sum"
).reset_index()
matrix["fiscal_year"] = matrix["fiscal_year"].astype(str)
pct_row = (matrix.iloc[1:2][["Continuation","New","Renewal"]].values -
           matrix.iloc[0:1][["Continuation","New","Renewal"]].values) / \
           matrix.iloc[0:1][["Continuation","New","Renewal"]].values * 100
pct_df = pd.DataFrame(pct_row, columns=["Continuation","New","Renewal"])
pct_df.insert(0, "fiscal_year", "% Change")
matrix = pd.concat([matrix, pct_df], ignore_index=True)
display = matrix.copy()
for col in ["Continuation", "New", "Renewal"]:
    display[col] = display[col].astype(object)

for col in ["Continuation", "New", "Renewal"]:
    for idx, row in display.iterrows():
        if row["fiscal_year"] == "% Change":
            display.at[idx, col] = f"{row[col]:.1f}%"
        else:
            display.at[idx, col] = f"${row[col]:.1f}B"

df_history = con.execute("""
 SELECT 
    fiscal_year, 
    award_type,
    COUNT(*) as grant_count,
    SUM(award_amount) / 1e9 as total_dollars
FROM main.nih_awards_national
WHERE award_type IN ('1','5','2')
	AND agency_code = 'NIH'
	AND fiscal_year BETWEEN 2014 AND 2025
GROUP BY fiscal_year, award_type
ORDER BY fiscal_year desc, award_type;
""").df()

df_new = df_history[df_history["award_type"] == "1"]
df_renewal = df_history[df_history["award_type"] == "2"]
df_continuation = df_history[df_history["award_type"] == "5"]

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=df_new["fiscal_year"],
    y=df_new["total_dollars"],
    stackgroup="one",
    name="New",
    fillcolor="#D65F5F"
))

fig.add_trace(go.Scatter(
    x=df_renewal["fiscal_year"],
    y=df_renewal["total_dollars"],
    stackgroup="one",
    name="Renewals",
    fillcolor="#6ACC65"
))


fig.add_trace(go.Scatter(
    x=df_continuation["fiscal_year"],
    y=df_continuation["total_dollars"],
    stackgroup="one",
    name="Continuations",
    fillcolor="#4878CF"
))


display = display.rename(columns={"fiscal_year": "Fiscal Year"})

st.plotly_chart(fig, use_container_width=True)
st.dataframe(display, hide_index=True)