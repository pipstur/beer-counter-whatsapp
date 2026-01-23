import rootutils

rootutils.setup_root(__file__, indicator="README.md", pythonpath=True)

from typing import List, Literal

import requests
import pandas as pd
import plotly.express as px
from plotly.graph_objs import Figure
import streamlit as st

from data.utils.db_utils import SUPABASE_URL, HEADERS_GET


AggregationLevel = Literal["Hour", "Day", "Week"]

INITIAL_BEER_COUNT = 73
CACHE_TTL_SEC = 300


@st.cache_data(ttl=CACHE_TTL_SEC)
def load_data() -> pd.DataFrame:
    response = requests.get(SUPABASE_URL, headers=HEADERS_GET)
    response.raise_for_status()
    df = pd.DataFrame(response.json())
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def filter_by_users(df: pd.DataFrame, users: List[str]) -> pd.DataFrame:
    return df[df["user_name"].isin(users)]


def filter_by_date_range(
    df: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> pd.DataFrame:
    return df[(df["timestamp"].dt.date >= start_date) & (df["timestamp"].dt.date <= end_date)]


def aggregate_beers(df: pd.DataFrame, level: AggregationLevel) -> pd.DataFrame:
    freq_map = {"Hour": "h", "Day": "D", "Week": "W"}
    return (
        df.groupby(pd.Grouper(key="timestamp", freq=freq_map[level]))["beer_count"]
        .sum()
        .reset_index()
    )


def render_total_metric(df: pd.DataFrame) -> None:
    total = int(df["beer_count"].sum()) + INITIAL_BEER_COUNT
    st.metric("Total Beers Drunk", total)


def render_total_timeline(df: pd.DataFrame, level: AggregationLevel) -> None:
    df_agg = aggregate_beers(df, level)
    fig = px.line(
        df_agg,
        x="timestamp",
        y="beer_count",
        markers=True,
        labels={"timestamp": "Time", "beer_count": "Beers"},
    )
    st.subheader("📊 Total Beers Over Time")
    st.plotly_chart(fig, width="stretch")


def render_leaderboard(df: pd.DataFrame) -> None:
    leaderboard = (
        df.groupby("user_name")["beer_count"]
        .sum()
        .sort_values(ascending=False)
        .head(15)
        .reset_index()
    )

    colors = ["gold" if i < 5 else "lightskyblue" for i in range(len(leaderboard))]

    fig = px.bar(
        leaderboard,
        x="beer_count",
        y="user_name",
        orientation="h",
        text="beer_count",
        labels={"beer_count": "Beers", "user_name": "User"},
        color=leaderboard.index,
        color_discrete_sequence=colors,
    )

    fig.update_layout(
        height=700,
        yaxis={"categoryorder": "total ascending"},
        showlegend=False,
    )

    st.subheader("🏆 Leaderboard (Top 15)")
    st.plotly_chart(fig, width="stretch")


def render_user_timelines(df: pd.DataFrame, users: List[str], level: AggregationLevel) -> None:
    st.subheader("📅 User Timelines")
    for user in users:
        user_df = df[df["user_name"] == user]
        if user_df.empty:
            continue

        df_agg = aggregate_beers(user_df, level)
        fig = px.line(
            df_agg,
            x="timestamp",
            y="beer_count",
            markers=True,
            title=user,
            labels={"timestamp": "Time", "beer_count": "Beers"},
        )
        st.plotly_chart(fig, width="stretch")


def render_beers_by_hour(df: pd.DataFrame) -> Figure:
    """Pie chart of beers consumed by hour of day (0–23)."""
    st.subheader("🕒 When Do We Drink?")

    if df.empty:
        return px.pie(title="No data available")

    df_hour = (
        df.assign(hour=df["timestamp"].dt.hour).groupby("hour", as_index=False)["beer_count"].sum()
    )

    df_hour["hour_label"] = df_hour["hour"].astype(str).str.zfill(2) + ":00"

    fig = px.pie(
        df_hour,
        names="hour_label",
        values="beer_count",
        hole=0.4,
        title="🕒 Beers by Hour of Day",
    )

    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(showlegend=True)

    st.plotly_chart(fig, width="stretch")


def main() -> None:
    st.title("🍺 Beer Tracker Dashboard")

    df = load_data()
    render_total_metric(df)

    # Sidebar filters
    st.sidebar.header("Filters")
    st.sidebar.header("View")

    view_mode = st.sidebar.radio(
        "Choose view",
        ["📈 Statistics", "👤 Users"],
    )
    users = sorted(df["user_name"].unique().tolist())
    selected_users = st.sidebar.multiselect("Users", users, default=users)

    filtered_df = filter_by_users(df, selected_users)

    if filtered_df.empty:
        st.sidebar.date_input("Start Date", disabled=True)
        st.sidebar.date_input("End Date", disabled=True)
        st.info("No data to display. Please select at least one user.")
        return

    dates = filtered_df["timestamp"].dt.date
    start_date = st.sidebar.date_input("Start Date", min(dates))
    end_date = st.sidebar.date_input("End Date", max(dates))

    filtered_df = filter_by_date_range(filtered_df, start_date, end_date)

    st.sidebar.header("Aggregation")
    agg_level: AggregationLevel = st.sidebar.selectbox(
        "Aggregate by", ["Hour", "Day", "Week"]
    )

    if view_mode == "📈 Statistics":
        render_total_timeline(filtered_df, agg_level)
        render_beers_by_hour(filtered_df)

    elif view_mode == "👤 Users":
        render_leaderboard(filtered_df)
        render_user_timelines(filtered_df, selected_users, agg_level)


if __name__ == "__main__":
    main()
