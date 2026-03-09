from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from datetime import date

from coach_features import (
    aggregate_daily_totals,
    build_weekly_win_message,
    compute_day_score,
    compute_logging_streak,
    suggest_meals_for_gaps,
)


def test_aggregate_and_streak():
    meals = [
        {"Logged At": "2026-03-07 10:00:00", "Calories": 100, "Protein (g)": 5, "Carbs (g)": 12, "Fat (g)": 3, "Fiber (g)": 1},
        {"Logged At": "2026-03-08 12:00:00", "Calories": 200, "Protein (g)": 10, "Carbs (g)": 25, "Fat (g)": 8, "Fiber (g)": 2},
        {"Logged At": "2026-03-08 20:00:00", "Calories": 300, "Protein (g)": 15, "Carbs (g)": 30, "Fat (g)": 10, "Fiber (g)": 3},
    ]
    daily = aggregate_daily_totals(meals)
    assert daily["2026-03-08"]["cal"] == 500
    assert daily["2026-03-08"]["prot"] == 25
    assert compute_logging_streak(daily, as_of=date(2026, 3, 8)) == 2


def test_compute_day_score_bounds():
    targets = {"cal": 2000, "prot": 130, "carb": 225, "fat": 65, "fiber": 25}
    low = compute_day_score({"cal": 400, "prot": 10, "carb": 40, "fat": 10, "fiber": 2}, targets)
    good = compute_day_score({"cal": 1950, "prot": 125, "carb": 215, "fat": 63, "fiber": 28}, targets)
    assert 0 <= low < good <= 100


def test_suggest_meals_for_gaps_and_message():
    seed = [
        ("Dal", "Curries", "1 cup", 180, 12, 20, 4, 8, "x"),
        ("Paneer", "Curries", "100g", 265, 18, 5, 20, 1, "x"),
        ("Sprouts", "Salads", "1 cup", 120, 10, 15, 1, 6, "x"),
    ]
    recs = suggest_meals_for_gaps(seed, {"prot": 30, "fiber": 12}, limit=2)
    assert len(recs) == 2
    assert "streak" in build_weekly_win_message(5, 81).lower()
