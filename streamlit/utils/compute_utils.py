from datetime import timedelta
import pandas as pd


def compute_achievements(df: pd.DataFrame) -> dict:
    df_tmp = df.copy()
    df_tmp["hour"] = df_tmp["timestamp"].dt.hour
    df_tmp["weekday"] = df_tmp["timestamp"].dt.day_name()

    achievements = {}

    def top_user(series: pd.Series):
        if series.empty:
            return None
        user = series.idxmax()
        return {
            "user": user,
            "value": int(series.loc[user]),
        }

    night_df = df_tmp[(df_tmp["hour"] >= 23) | (df_tmp["hour"] < 4)]
    achievements["Noćna ptica 🦉"] = top_user(night_df.groupby("user_name")["beer_count"].sum())

    early_df = df_tmp[(df_tmp["hour"] >= 4) & (df_tmp["hour"] < 11)]
    achievements["Ranoranilac 🌅"] = top_user(early_df.groupby("user_name")["beer_count"].sum())

    weekend_df = df_tmp[
        ((df_tmp["weekday"] == "Friday") & (df_tmp["hour"] >= 18))
        | (df_tmp["weekday"].isin(["Saturday", "Sunday"]))
    ]
    achievements["Vikendaš 🏖️"] = top_user(weekend_df.groupby("user_name")["beer_count"].sum())

    df_sorted = df_tmp.sort_values(["user_name", "timestamp"])
    session_results = []

    for user, group in df_sorted.groupby("user_name"):
        prev_time = None
        session_total = max_total = 0

        for _, row in group.iterrows():
            if prev_time is None or (row["timestamp"] - prev_time) <= timedelta(hours=3):
                session_total += row["beer_count"]
            else:
                max_total = max(max_total, session_total)
                session_total = row["beer_count"]
            prev_time = row["timestamp"]

        session_results.append((user, max(max_total, session_total)))

    achievements["Sprinter ⚡"] = (
        {
            "user": max(session_results, key=lambda x: x[1])[0],
            "value": max(session_results, key=lambda x: x[1])[1],
        }
        if session_results
        else None
    )

    streak_results = []

    for user, group in df_tmp.groupby("user_name"):
        days = sorted(group["timestamp"].dt.date.unique())
        max_streak = streak = 1

        for i in range(1, len(days)):
            streak = streak + 1 if (days[i] - days[i - 1]).days == 1 else 1
            max_streak = max(max_streak, streak)

        streak_results.append((user, max_streak))

    achievements["Maratonac 🏃"] = (
        {
            "user": max(streak_results, key=lambda x: x[1])[0],
            "value": max(streak_results, key=lambda x: x[1])[1],
        }
        if streak_results
        else None
    )

    best = None
    best_value = 0

    for user, group in df_sorted.groupby("user_name"):
        prev_time = None
        for _, row in group.iterrows():
            if prev_time is not None and (row["timestamp"] - prev_time).days >= 7:
                window_sum = group[
                    (group["timestamp"] >= row["timestamp"])
                    & (group["timestamp"] <= row["timestamp"] + timedelta(days=3))
                ]["beer_count"].sum()

                if window_sum > best_value:
                    best_value = window_sum
                    best = user
            prev_time = row["timestamp"]

    achievements["Povratak kralja 👑"] = (
        {"user": best, "value": best_value} if best is not None else None
    )

    return achievements


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
