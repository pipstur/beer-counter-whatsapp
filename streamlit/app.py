from datetime import timedelta
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
WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


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


def render_cumulative_global(df: pd.DataFrame) -> None:
    df_sorted = df.sort_values("timestamp")
    df_sorted["cumulative"] = df_sorted["beer_count"].cumsum() + INITIAL_BEER_COUNT

    fig = px.line(
        df_sorted,
        x="timestamp",
        y="cumulative",
        labels={"cumulative": "Total Beers"},
        title="📈 Cumulative Beers (Global)",
    )
    st.plotly_chart(fig, width="stretch")


def render_hour_weekday_heatmap(df: pd.DataFrame) -> None:
    df_tmp = df.copy()
    df_tmp["hour_bin"] = (df_tmp["timestamp"].dt.hour // 4) * 4
    df_tmp["hour_label"] = (
        df_tmp["hour_bin"].astype(str).str.zfill(2)
        + "–"
        + (df_tmp["hour_bin"] + 3).astype(str).str.zfill(2)
    )
    df_tmp["weekday"] = pd.Categorical(
        df_tmp["timestamp"].dt.day_name(), categories=WEEKDAY_ORDER, ordered=True
    )

    heatmap_df = (
        df_tmp.groupby(["weekday", "hour_label"])["beer_count"]
        .sum()
        .unstack(fill_value=0)
        .reindex(WEEKDAY_ORDER)
    )

    fig = px.imshow(
        heatmap_df,
        labels=dict(x="Time of Day", y="Weekday", color="Beers"),
        x=heatmap_df.columns,
        y=heatmap_df.index,
        text_auto=True,
        aspect="auto",
        title="Beers by Time of Day & Weekday",
    )
    fig.update_layout(yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, width="stretch")


def render_cumulative_per_user(df: pd.DataFrame) -> None:
    top_users = df.groupby("user_name")["beer_count"].sum().nlargest(15).index
    df_filtered = df[df["user_name"].isin(top_users)].sort_values("timestamp").copy()
    df_filtered["cumulative"] = df_filtered.groupby("user_name")["beer_count"].cumsum()

    fig = px.line(
        df_filtered,
        x="timestamp",
        y="cumulative",
        color="user_name",
        title="📈 Cumulative Beers per User (Top 15)",
    )
    st.plotly_chart(fig, width="stretch")


def render_rank_over_time(df: pd.DataFrame) -> None:
    df_week = (
        df.assign(week=df["timestamp"].dt.to_period("W").astype(str))
        .groupby(["week", "user_name"])["beer_count"]
        .sum()
        .reset_index()
    )
    weeks, users = df_week["week"].unique(), df_week["user_name"].unique()
    full_index = pd.MultiIndex.from_product([weeks, users], names=["week", "user_name"])
    df_full = (
        df_week.set_index(["week", "user_name"]).reindex(full_index, fill_value=0).reset_index()
    )
    df_full["cumulative"] = df_full.groupby("user_name")["beer_count"].cumsum()

    top_users = df_full.groupby("user_name")["cumulative"].max().nlargest(10).index
    df_full = df_full[df_full["user_name"].isin(top_users)]
    df_full["rank"] = df_full.groupby("week")["cumulative"].rank(method="first", ascending=False)
    df_full = df_full[df_full["rank"] <= 10]

    fig = px.bar(
        df_full,
        x="cumulative",
        y="rank",
        color="user_name",
        text="user_name",
        animation_frame="week",
        orientation="h",
        range_y=[15.5, 0.5],
        title="🏁 Cumulative Leaderboard Race (Weekly, Top 15)",
        labels={"cumulative": "Total Beers", "rank": "Rank"},
    )
    fig.update_traces(textposition="inside")
    fig.update_layout(yaxis=dict(tickmode="linear", dtick=1, autorange=False), showlegend=True)
    st.plotly_chart(fig, width="stretch")


def compute_achievements(df: pd.DataFrame) -> dict:
    df_tmp = df.copy()
    df_tmp["hour"], df_tmp["weekday"] = (
        df_tmp["timestamp"].dt.hour,
        df_tmp["timestamp"].dt.day_name(),
    )
    achievements = {}

    night_df = df_tmp[(df_tmp["hour"] >= 23) | (df_tmp["hour"] < 4)]
    achievements["Night Owl 🦉"] = (
        night_df.groupby("user_name")["beer_count"].sum().idxmax() if not night_df.empty else None
    )

    early_df = df_tmp[(df_tmp["hour"] >= 4) & (df_tmp["hour"] < 11)]
    achievements["Early Bird 🌅"] = (
        early_df.groupby("user_name")["beer_count"].sum().idxmax() if not early_df.empty else None
    )

    weekend_df = df_tmp[
        ((df_tmp["weekday"] == "Friday") & (df_tmp["hour"] >= 18))
        | (df_tmp["weekday"].isin(["Saturday", "Sunday"]))
    ]
    achievements["Weekend Warrior 🏖️"] = (
        weekend_df.groupby("user_name")["beer_count"].sum().idxmax()
        if not weekend_df.empty
        else None
    )

    df_sorted = df_tmp.sort_values(["user_name", "timestamp"])
    sessions = []
    for user, group in df_sorted.groupby("user_name"):
        group = group.reset_index(drop=True)
        session_total, max_total, prev_time = 0, 0, None
        for _, row in group.iterrows():
            if prev_time is None or (row["timestamp"] - prev_time) <= timedelta(hours=3):
                session_total += row["beer_count"]
            else:
                max_total = max(max_total, session_total)
                session_total = row["beer_count"]
            prev_time = row["timestamp"]
        sessions.append((user, max(max_total, session_total)))
    achievements["Sprinter ⚡"] = max(sessions, key=lambda x: x[1])[0] if sessions else None

    streaks = []
    for user, group in df_tmp.groupby("user_name"):
        days = sorted(group["timestamp"].dt.date.unique())
        max_streak, streak = 0, 1
        for i in range(1, len(days)):
            streak = streak + 1 if (days[i] - days[i - 1]).days == 1 else 1
            max_streak = max(max_streak, streak)
        streaks.append((user, max_streak))
    achievements["Maratonac 🏃"] = max(streaks, key=lambda x: x[1])[0] if streaks else None

    best_user = None
    for user, group in df_sorted.groupby("user_name"):
        group = group.reset_index(drop=True)
        prev_time, max_jump = None, 0
        for _, row in group.iterrows():
            if prev_time is None:
                prev_time = row["timestamp"]
                continue
            gap = (row["timestamp"] - prev_time).days
            if gap >= 7:
                jump_sum = group[
                    (group["timestamp"] >= row["timestamp"])
                    & (group["timestamp"] <= row["timestamp"] + timedelta(days=3))
                ]["beer_count"].sum()
                if jump_sum > max_jump:
                    max_jump, best_user = jump_sum, user
            prev_time = row["timestamp"]
    achievements["Comeback Kid 🔥"] = best_user

    return achievements


def render_achievements(df: pd.DataFrame) -> None:
    if df["user_name"].nunique() < 2:
        st.warning("Please select at least two users to compute achievements.")
        return
    st.subheader("🏆 Achievements / Fun Titles")
    achievements = compute_achievements(df)
    cols = st.columns(3)
    for i, (title, user) in enumerate(achievements.items()):
        cols[i % 3].metric(title, user)


def compute_user_features(df: pd.DataFrame) -> pd.DataFrame:
    df_tmp = df.copy()
    df_tmp["hour"], df_tmp["weekday"], df_tmp["date"] = (
        df_tmp["timestamp"].dt.hour,
        df_tmp["timestamp"].dt.day_name(),
        df_tmp["timestamp"].dt.date,
    )
    features = []
    for user, group in df_tmp.groupby("user_name"):
        total = group["beer_count"].sum()
        night_ratio = (
            group[(group["hour"] >= 23) | (group["hour"] < 4)]["beer_count"].sum() / total
        )
        weekend_ratio = (
            group[group["weekday"].isin(["Friday", "Saturday", "Sunday"])]["beer_count"].sum()
            / total
        )
        g, sessions, prev_time = group.sort_values("timestamp").reset_index(drop=True), [], None
        for _, row in g.iterrows():
            if prev_time is None or (row["timestamp"] - prev_time) <= timedelta(hours=3):
                sessions_total = (
                    row["beer_count"] if prev_time is None else sessions_total + row["beer_count"]
                )
            else:
                sessions.append(sessions_total)
                sessions_total = row["beer_count"]
            prev_time = row["timestamp"]
        sessions.append(sessions_total)
        features.append(
            {
                "user_name": user,
                "night_ratio": night_ratio,
                "weekend_ratio": weekend_ratio,
                "avg_per_session": sum(sessions) / len(sessions),
                "active_days": group["date"].nunique(),
                "avg_per_day": total / group["date"].nunique(),
            }
        )
    return pd.DataFrame(features)


def render_who_drinks_like_whom(df: pd.DataFrame) -> None:
    st.subheader("🧬 Who Drinks Like Whom")
    features_df = compute_user_features(df)
    features_df["short_name"] = features_df["user_name"].str[:5]
    numeric_cols = [c for c in features_df.columns if c not in ["user_name", "short_name"]]
    x_feat, y_feat = st.selectbox("X-axis feature", numeric_cols, index=3), st.selectbox(
        "Y-axis feature", numeric_cols, index=4
    )
    fig = px.scatter(
        features_df,
        x=x_feat,
        y=y_feat,
        text="short_name",
        color="short_name",
        title="Behavioral Similarity Scatter",
        hover_data=numeric_cols + ["user_name"],
    )
    fig.update_traces(textposition="top center")
    st.plotly_chart(fig, width="stretch")


def render_carry_of_week(df: pd.DataFrame) -> None:
    st.subheader("⚖️ Carry of the Week")
    df_tmp = df.copy()
    df_tmp["week"] = df_tmp["timestamp"].dt.to_period("W").astype(str)
    weekly = df_tmp.groupby(["week", "user_name"])["beer_count"].sum().reset_index()
    weekly_total = (
        weekly.groupby("week")["beer_count"]
        .sum()
        .reset_index()
        .rename(columns={"beer_count": "total_beers"})
    )
    merged = weekly.merge(weekly_total, on="week")
    merged["pct"] = merged["beer_count"] / merged["total_beers"] * 100
    top_users = merged.loc[merged.groupby("week")["pct"].idxmax()]
    all_weeks = pd.DataFrame({"week": merged["week"].unique()})
    final_df = all_weeks.merge(top_users, on="week", how="left")
    final_df["Top User"] = final_df.apply(
        lambda row: (
            row["user_name"]
            if pd.notnull(row["pct"]) and row["pct"] > 4
            else "No significant carry"
        ),
        axis=1,
    )
    final_df["Beers Drunk"] = final_df.apply(
        lambda row: int(row["beer_count"]) if pd.notnull(row["pct"]) and row["pct"] > 4 else 0,
        axis=1,
    )
    final_df["% of Total"] = final_df.apply(
        lambda row: round(row["pct"], 1) if pd.notnull(row["pct"]) and row["pct"] > 4 else 0,
        axis=1,
    )
    st.table(
        final_df.sort_values("week", ascending=False)[
            ["week", "Top User", "Beers Drunk", "% of Total"]
        ].rename(columns={"week": "Week"})
    )


def render_regular_vs_chaos(df: pd.DataFrame) -> None:
    st.subheader("📊 Regularity vs Chaos")
    df_tmp = df.copy()
    df_tmp["date"] = df_tmp["timestamp"].dt.date
    features = [
        {
            "user_name": user,
            "short_name": user[:5],
            "active_days": group["date"].nunique(),
            "avg_per_day": group.groupby("date")["beer_count"].sum().mean(),
        }
        for user, group in df_tmp.groupby("user_name")
    ]
    feat_df = pd.DataFrame(features)
    fig = px.scatter(
        feat_df,
        x="active_days",
        y="avg_per_day",
        text="short_name",
        color="short_name",
        title="Regularity vs Average Consumption",
        hover_data=["user_name", "active_days", "avg_per_day"],
    )
    fig.update_traces(textposition="top center")
    st.plotly_chart(fig, width="stretch")


def render_fun_and_patterns(df: pd.DataFrame) -> None:
    st.header("🎉 Fun & Patterns")
    render_achievements(df)
    st.markdown("---")
    render_who_drinks_like_whom(df)
    st.markdown("---")
    render_carry_of_week(df)
    st.markdown("---")
    render_regular_vs_chaos(df)


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
        render_total_timeline(filtered_df, agg_level)
        render_cumulative_global(filtered_df)
        render_beers_by_hour(filtered_df)
        render_hour_weekday_heatmap(filtered_df)
    elif view_mode == "👤 Users":
        render_leaderboard(filtered_df)
        render_cumulative_per_user(filtered_df)
        render_rank_over_time(filtered_df)
        render_user_timelines(filtered_df, selected_users, agg_level)
    elif view_mode == "🏆 Fun & Patterns":
        render_fun_and_patterns(filtered_df)


if __name__ == "__main__":
    main()
