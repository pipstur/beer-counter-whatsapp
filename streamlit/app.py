import rootutils

rootutils.setup_root(__file__, indicator="README.md", pythonpath=True)

import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from data.utils.db_utils import SUPABASE_URL, HEADERS_GET


@st.cache_data(ttl=300)  # cache for 5 min
def load_data():
    r = requests.get(SUPABASE_URL, headers=HEADERS_GET)
    r.raise_for_status()
    data = pd.DataFrame(r.json())
    data["timestamp"] = pd.to_datetime(data["timestamp"])
    return data


df = load_data()

st.title("🍺 Beer Tracker Dashboard")

# Total beers (with optional starting offset)
total_beers = df["beer_count"].sum() + 76
st.metric("Total Beers Drunk", total_beers)

# Sidebar filters
st.sidebar.header("Filters")
users = df["user_name"].unique().tolist()
selected_users = st.sidebar.multiselect("Select Users", users, default=users)
filtered_df = df[df["user_name"].isin(selected_users)]

# Date range filter
dates = filtered_df["timestamp"].dt.date
start_date = st.sidebar.date_input("Start Date", min(dates))
end_date = st.sidebar.date_input("End Date", max(dates))
if start_date is not None and end_date is not None:
    filtered_df = filtered_df[
        (filtered_df["timestamp"].dt.date >= start_date)
        & (filtered_df["timestamp"].dt.date <= end_date)
    ]
else:
    st.sidebar.error("Empty data")

# Aggregation level dropdown
st.sidebar.header("Aggregation")
agg_level = st.sidebar.selectbox("Aggregate beers by", ["Day", "Hour", "Week"])


# Function to aggregate
def aggregate_beers(df: pd.DataFrame, level: str) -> pd.DataFrame:
    if level == "Hour":
        df_agg = (
            df.groupby(pd.Grouper(key="timestamp", freq="h"))["beer_count"].sum().reset_index()
        )
    elif level == "Day":
        df_agg = (
            df.groupby(pd.Grouper(key="timestamp", freq="D"))["beer_count"].sum().reset_index()
        )
    elif level == "Week":
        df_agg = (
            df.groupby(pd.Grouper(key="timestamp", freq="W"))["beer_count"].sum().reset_index()
        )
    return df_agg


# Aggregate data for all users (total)
df_total = aggregate_beers(filtered_df, agg_level)

st.subheader("📊 Total Beers Over Time")
fig_total = px.line(
    df_total,
    x="timestamp",
    y="beer_count",
    markers=True,
    labels={"timestamp": "Time", "beer_count": "Beers"},
)
st.plotly_chart(fig_total, width="stretch")

# Leaderboard
st.subheader("🏆 Leaderboard (Top 15)")

# Aggregate and sort
leaderboard = (
    filtered_df.groupby("user_name")["beer_count"].sum().sort_values(ascending=False).reset_index()
)

# Take top 15
leaderboard_top = leaderboard.head(15)

# Assign colors: top 5 get a special color, others default
colors = ["gold" if i < 5 else "lightskyblue" for i in range(len(leaderboard_top))]

fig = px.bar(
    leaderboard_top,
    x="beer_count",
    y="user_name",
    orientation="h",
    text="beer_count",
    labels={"beer_count": "Beers", "user_name": "User"},
    color=leaderboard_top.index,  # temporary index to assign colors
    color_discrete_sequence=colors,
)

# Make bars taller to fit names
fig.update_layout(height=700, yaxis={"categoryorder": "total ascending"}, showlegend=False)

st.plotly_chart(fig, width="stretch")

# User timelines
st.subheader("📅 User Timelines")
for user in selected_users:
    user_df = filtered_df[filtered_df["user_name"] == user]
    if not user_df.empty:
        df_user = aggregate_beers(user_df, agg_level)
        fig_user = px.line(
            df_user,
            x="timestamp",
            y="beer_count",
            markers=True,
            title=user,
            labels={"timestamp": "Time", "beer_count": "Beers"},
        )
        st.plotly_chart(fig_user, width="stretch")
