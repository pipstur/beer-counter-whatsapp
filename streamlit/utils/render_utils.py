import rootutils

from .compute_utils import (
    compute_achievements,
    compute_user_features,
)

rootutils.setup_root(__file__, indicator="README.md", pythonpath=True)

from typing import List, Literal

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import ACHIEVEMENT_INFO, INITIAL_BEER_COUNT, WEEKDAY_ORDER, AGG_FREQ_MAP

AggregationLevel = Literal["Hour", "Day", "Week"]


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


def render_beers_by_hour(df: pd.DataFrame) -> None:
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


def render_cumulative_global(df: pd.DataFrame, agg_level: AggregationLevel) -> None:
    freq = AGG_FREQ_MAP[agg_level]

    df_agg = (
        df.groupby(pd.Grouper(key="timestamp", freq=freq))["beer_count"]
        .sum()
        .reset_index()
        .sort_values("timestamp")
    )

    df_agg["cumulative"] = df_agg["beer_count"].cumsum() + INITIAL_BEER_COUNT

    fig = px.line(
        df_agg,
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
        df_tmp.groupby(["weekday", "hour_label"], observed=True)["beer_count"]
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


def render_cumulative_per_user(df: pd.DataFrame, agg_level: AggregationLevel) -> None:
    freq = AGG_FREQ_MAP[agg_level]

    top_users = df.groupby("user_name")["beer_count"].sum().nlargest(15).index

    df_filtered = df[df["user_name"].isin(top_users)].copy()

    df_agg = (
        df_filtered.groupby(
            [
                "user_name",
                pd.Grouper(key="timestamp", freq=freq),
            ]
        )["beer_count"]
        .sum()
        .reset_index()
        .sort_values("timestamp")
    )

    df_agg["cumulative"] = df_agg.groupby("user_name")["beer_count"].cumsum()

    fig = px.line(
        df_agg,
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


def render_achievements(df: pd.DataFrame) -> None:
    achievements = compute_achievements(df)

    st.subheader("🏆 Dostignuća")

    cols = st.columns(2)
    col_idx = 0

    for title, result in achievements.items():
        info = ACHIEVEMENT_INFO[title]
        description = info["description"]
        unit = info.get("unit", "")

        with cols[col_idx]:
            if result is None:
                st.metric(
                    label=title,
                    value="—",
                    help=f"Nema dovoljno podataka.\n\n{description}",
                )
            else:
                value_text = f'{result["value"]} {unit}'.strip() if unit else str(result["value"])

                st.metric(
                    label=title,
                    value=result["user"],
                    delta=value_text,
                    help=description,
                )

        col_idx = (col_idx + 1) % 2


def render_who_drinks_like_whom(df: pd.DataFrame) -> None:
    st.subheader("🧬 Who Drinks Like Whom")
    st.info(
        """Select two features to visualize user similarities in drinking behavior.
        Users with similar habits will cluster together."""
    )
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
    st.info(
        """The 'Carry of the Week' is awarded to the user who consumes more than 4% of the
        total beers in a given week. If no user exceeds this threshold, the title is not awarded"""
    )
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
    st.info(
        """On the X-axis: Number of active days (days with at least one beer).
        On the Y-axis: Average beers consumed per active day.
        Regular drinkers appear towards the right side, while chaotic drinkers are
        towards the upper left"""
    )

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


def aggregate_beers(df: pd.DataFrame, level: AggregationLevel) -> pd.DataFrame:
    freq_map = {"Hour": "h", "Day": "D", "Week": "W"}
    return (
        df.groupby(pd.Grouper(key="timestamp", freq=freq_map[level]))["beer_count"]
        .sum()
        .reset_index()
    )


def render_statistics_view(filtered_df: pd.DataFrame, agg_level: AggregationLevel) -> None:
    st.header("📈 Statistics")
    render_total_timeline(filtered_df, agg_level)
    st.markdown("---")
    render_cumulative_global(filtered_df, agg_level)
    st.markdown("---")
    render_beers_by_hour(filtered_df)
    st.markdown("---")
    render_hour_weekday_heatmap(filtered_df)


def render_users_view(
    filtered_df: pd.DataFrame, selected_users: List[str], agg_level: AggregationLevel
) -> None:
    st.header("👤 Users")
    render_leaderboard(filtered_df)
    st.markdown("---")
    render_cumulative_per_user(filtered_df, agg_level)
    st.markdown("---")
    render_rank_over_time(filtered_df)
    st.markdown("---")
    render_user_timelines(filtered_df, selected_users, agg_level)


def render_fun_and_patterns(df: pd.DataFrame) -> None:
    st.header("🎉 Fun & Patterns")
    render_achievements(df)
    st.markdown("---")
    render_who_drinks_like_whom(df)
    st.markdown("---")
    render_carry_of_week(df)
    st.markdown("---")
    render_regular_vs_chaos(df)
