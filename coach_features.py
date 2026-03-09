from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Tuple


def _to_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def aggregate_daily_totals(meals: Iterable[dict]) -> Dict[str, dict]:
    """Aggregate nutrition totals by YYYY-MM-DD from meal records."""
    daily: Dict[str, dict] = {}
    for meal in meals:
        day = str(meal.get("Logged At", ""))[:10]
        if not day:
            continue
        bucket = daily.setdefault(
            day,
            {"cal": 0.0, "prot": 0.0, "carb": 0.0, "fat": 0.0, "fiber": 0.0, "meals": 0},
        )
        bucket["cal"] += _to_float(meal.get("Calories", 0))
        bucket["prot"] += _to_float(meal.get("Protein (g)", 0))
        bucket["carb"] += _to_float(meal.get("Carbs (g)", 0))
        bucket["fat"] += _to_float(meal.get("Fat (g)", 0))
        bucket["fiber"] += _to_float(meal.get("Fiber (g)", 0))
        bucket["meals"] += 1
    return daily


def compute_logging_streak(daily_totals: Dict[str, dict], as_of: date | None = None) -> int:
    """Count consecutive days with at least one meal up to as_of date."""
    check_day = as_of or date.today()
    streak = 0
    while check_day.isoformat() in daily_totals:
        streak += 1
        check_day -= timedelta(days=1)
    return streak


def compute_day_score(totals: dict, targets: dict) -> int:
    """Simple score from adherence to calorie/protein/carbs/fat/fiber goals."""
    if not totals:
        return 0

    def closeness(actual: float, target: float, tolerance: float) -> float:
        if target <= 0:
            return 1.0
        diff_ratio = abs(actual - target) / max(target, 1)
        return max(0.0, 1.0 - (diff_ratio / tolerance))

    cal_score = closeness(_to_float(totals.get("cal")), targets.get("cal", 0), 0.45)
    prot_score = closeness(_to_float(totals.get("prot")), targets.get("prot", 0), 0.60)
    carb_score = closeness(_to_float(totals.get("carb")), targets.get("carb", 0), 0.60)
    fat_score = closeness(_to_float(totals.get("fat")), targets.get("fat", 0), 0.60)

    fiber_actual = _to_float(totals.get("fiber"))
    fiber_target = targets.get("fiber", 25)
    fiber_score = min(fiber_actual / max(fiber_target, 1), 1.0)

    weighted = (cal_score * 0.30 + prot_score * 0.25 + carb_score * 0.15 + fat_score * 0.15 + fiber_score * 0.15)
    return int(round(weighted * 100))


def suggest_meals_for_gaps(food_seed: List[Tuple], gaps: dict, limit: int = 3) -> List[dict]:
    """Suggest meals that best cover protein/fiber deficits while controlling calories."""
    if not food_seed:
        return []

    target_prot = max(_to_float(gaps.get("prot", 0)), 0)
    target_fiber = max(_to_float(gaps.get("fiber", 0)), 0)

    ranked = []
    for item in food_seed:
        name, category, serving, cal, prot, carbs, fat, fiber, _ = item
        cal = _to_float(cal)
        prot = _to_float(prot)
        fiber = _to_float(fiber)

        # Higher score for protein/fiber density and relevance to current gap
        relevance = (min(prot, target_prot) * 2.2) + (min(fiber, target_fiber) * 2.8)
        density = (prot * 1.4 + fiber * 2.0) / max(cal, 1)
        score = relevance + density * 120

        ranked.append(
            {
                "name": name,
                "category": category,
                "serving": serving,
                "cal": int(round(cal)),
                "prot": round(prot, 1),
                "fiber": round(fiber, 1),
                "score": score,
            }
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)

    seen_cats = set()
    picks = []
    for row in ranked:
        if row["category"] in seen_cats and len(picks) < 2:
            continue
        picks.append(row)
        seen_cats.add(row["category"])
        if len(picks) >= limit:
            break
    return picks


def build_weekly_win_message(streak: int, avg_score: float) -> str:
    if streak >= 10:
        return f"🔥 {streak}-day streak! You're in elite consistency mode. Avg score: {avg_score:.0f}/100."
    if streak >= 5:
        return f"💪 {streak}-day streak! Excellent momentum. Avg score: {avg_score:.0f}/100."
    if streak >= 2:
        return f"🌱 {streak}-day streak! Keep showing up — it's working. Avg score: {avg_score:.0f}/100."
    return f"✨ Fresh start today. Log 2+ days in a row to unlock streak mode. Avg score: {avg_score:.0f}/100."
