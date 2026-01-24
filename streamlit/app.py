import rootutils

rootutils.setup_root(__file__, indicator="README.md", pythonpath=True)

from typing import List
from utils.render_utils import (
    render_fun_and_patterns,
    render_statistics_view,
    render_total_metric,
    render_users_view,
)
from utils import CACHE_TTL_SEC
import requests
import pandas as pd
import streamlit as st

from data.utils.db_utils import SUPABASE_URL, HEADERS_GET
from utils.render_utils import AggregationLevel


@st.cache_data(ttl=CACHE_TTL_SEC)
def load_data() -> pd.DataFrame:
    page_size = 1000
    offset = 0
    rows: list[dict] = []

    while True:
        response = requests.get(
            SUPABASE_URL,
            headers={
                **HEADERS_GET,
                "Range": f"{offset}-{offset + page_size - 1}",
            },
        )
        response.raise_for_status()

        batch = response.json()
        if not batch:
            break

        rows.extend(batch)
        offset += page_size

    if not rows:
        return pd.DataFrame(columns=["timestamp"])

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def filter_by_users(df: pd.DataFrame, users: List[str]) -> pd.DataFrame:
    return df[df["user_name"].isin(users)]


def filter_by_date_range(
    df: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> pd.DataFrame:
    return df[(df["timestamp"].dt.date >= start_date) & (df["timestamp"].dt.date <= end_date)]


def main() -> None:
    st.title("🍺 Beer Tracker Dashboard")

    df = load_data()
    render_total_metric(df)

    st.sidebar.header("Filters")
    st.sidebar.header("View")

    view_mode = st.sidebar.radio(
        "Choose view",
        ["📈 Statistics", "👤 Users", "🏆 Fun & Patterns"],
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
    agg_level: AggregationLevel = st.sidebar.selectbox("Aggregate by", ["Hour", "Day", "Week"])

    if view_mode == "📈 Statistics":
        render_statistics_view(filtered_df, agg_level)
    elif view_mode == "👤 Users":
        render_users_view(filtered_df, selected_users, agg_level)
    elif view_mode == "🏆 Fun & Patterns":
        render_fun_and_patterns(filtered_df)


if __name__ == "__main__":
    main()
