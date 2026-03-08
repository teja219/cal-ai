import streamlit as st
import anthropic
import base64
import json
import os
from datetime import datetime, date
from PIL import Image
import io
import math

import gspread
from google.oauth2.service_account import Credentials

# ── Google Sheets config ──────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SHEET_MEALS  = "Meals"
SHEET_DAILY  = "Daily Summary"

MEAL_HEADERS = [
    "ID", "Logged At", "Food Name", "Serving Size",
    "Calories", "Protein (g)", "Carbs (g)", "Fat (g)",
    "Fiber (g)", "Sugar (g)", "Health Score", "Confidence (%)",
    "Tips", "Ingredients (JSON)",
]
DAILY_HEADERS = [
    "Date", "Meals", "Total Calories", "Total Protein (g)",
    "Total Carbs (g)", "Total Fat (g)",
]

# ── User Profile (80kg, 5'3") ─────────────────────────────────────────────────
USER_WEIGHT_KG = 80
USER_HEIGHT_CM = 160.02  # 5'3"
# BMR using Mifflin-St Jeor (assuming 30yo, moderate activity; adjust if needed)
# For a male: BMR = 10*w + 6.25*h - 5*a + 5; TDEE ~ BMR * 1.55
# For a female: BMR = 10*w + 6.25*h - 5*a - 161; TDEE ~ BMR * 1.55
# Using gender-neutral conservative estimate:
USER_BMR = 10 * USER_WEIGHT_KG + 6.25 * USER_HEIGHT_CM - 5 * 25 - 78  # ~female default
USER_TDEE = round(USER_BMR * 1.375)  # lightly active
DAILY_CALORIE_TARGET = USER_TDEE
PROTEIN_TARGET_G = round(USER_WEIGHT_KG * 1.6)   # 1.6g/kg
CARBS_TARGET_G   = round(DAILY_CALORIE_TARGET * 0.45 / 4)
FAT_TARGET_G     = round(DAILY_CALORIE_TARGET * 0.30 / 9)

# ── Indian Food Database ──────────────────────────────────────────────────────
INDIAN_FOOD_DB = {
    # Breakfast
    "Idli (1 piece)": {"calories": 39, "protein_g": 2, "carbs_g": 8, "fat_g": 0.4, "fiber_g": 0.5},
    "Dosa (1 plain)": {"calories": 133, "protein_g": 3, "carbs_g": 25, "fat_g": 2.5, "fiber_g": 1},
    "Masala Dosa": {"calories": 220, "protein_g": 5, "carbs_g": 38, "fat_g": 6, "fiber_g": 2},
    "Poha (1 cup)": {"calories": 180, "protein_g": 3.5, "carbs_g": 33, "fat_g": 4, "fiber_g": 2},
    "Upma (1 cup)": {"calories": 200, "protein_g": 5, "carbs_g": 32, "fat_g": 6, "fiber_g": 2},
    "Paratha (1 plain)": {"calories": 200, "protein_g": 4, "carbs_g": 30, "fat_g": 7, "fiber_g": 2},
    "Aloo Paratha": {"calories": 260, "protein_g": 5, "carbs_g": 40, "fat_g": 9, "fiber_g": 3},
    "Besan Chilla (1)": {"calories": 120, "protein_g": 6, "carbs_g": 16, "fat_g": 3, "fiber_g": 2},
    "Medu Vada (1)": {"calories": 97, "protein_g": 3.5, "carbs_g": 12, "fat_g": 4, "fiber_g": 1},
    "Pongal (1 cup)": {"calories": 220, "protein_g": 6, "carbs_g": 36, "fat_g": 6, "fiber_g": 2},
    # Rice dishes
    "Steamed Rice (1 cup cooked)": {"calories": 206, "protein_g": 4, "carbs_g": 45, "fat_g": 0.4, "fiber_g": 0.6},
    "Jeera Rice (1 cup)": {"calories": 250, "protein_g": 4.5, "carbs_g": 46, "fat_g": 5, "fiber_g": 1},
    "Biryani Chicken (1 plate ~350g)": {"calories": 490, "protein_g": 28, "carbs_g": 55, "fat_g": 15, "fiber_g": 2},
    "Biryani Veg (1 plate ~350g)": {"calories": 380, "protein_g": 8, "carbs_g": 60, "fat_g": 10, "fiber_g": 4},
    "Curd Rice (1 cup)": {"calories": 175, "protein_g": 5, "carbs_g": 30, "fat_g": 4, "fiber_g": 1},
    "Lemon Rice (1 cup)": {"calories": 230, "protein_g": 4, "carbs_g": 42, "fat_g": 5, "fiber_g": 1.5},
    "Sambar Rice (1 cup)": {"calories": 210, "protein_g": 6, "carbs_g": 38, "fat_g": 4, "fiber_g": 3},
    # Breads
    "Roti/Chapati (1)": {"calories": 71, "protein_g": 2.6, "carbs_g": 15, "fat_g": 0.4, "fiber_g": 2},
    "Puri (1)": {"calories": 116, "protein_g": 2, "carbs_g": 16, "fat_g": 5, "fiber_g": 1},
    "Naan (1)": {"calories": 262, "protein_g": 8, "carbs_g": 45, "fat_g": 6, "fiber_g": 2},
    # Curries & Dals
    "Dal Tadka (1 cup)": {"calories": 190, "protein_g": 11, "carbs_g": 28, "fat_g": 5, "fiber_g": 7},
    "Dal Makhani (1 cup)": {"calories": 250, "protein_g": 12, "carbs_g": 30, "fat_g": 9, "fiber_g": 8},
    "Chana Masala (1 cup)": {"calories": 270, "protein_g": 14, "carbs_g": 42, "fat_g": 6, "fiber_g": 12},
    "Rajma (1 cup)": {"calories": 240, "protein_g": 15, "carbs_g": 40, "fat_g": 4, "fiber_g": 10},
    "Paneer Butter Masala (1 cup)": {"calories": 350, "protein_g": 16, "carbs_g": 18, "fat_g": 24, "fiber_g": 2},
    "Palak Paneer (1 cup)": {"calories": 280, "protein_g": 14, "carbs_g": 12, "fat_g": 20, "fiber_g": 3},
    "Butter Chicken (1 cup)": {"calories": 320, "protein_g": 25, "carbs_g": 14, "fat_g": 18, "fiber_g": 2},
    "Chicken Tikka Masala (1 cup)": {"calories": 310, "protein_g": 28, "carbs_g": 12, "fat_g": 17, "fiber_g": 2},
    "Aloo Sabzi (1 cup)": {"calories": 180, "protein_g": 3, "carbs_g": 28, "fat_g": 7, "fiber_g": 3},
    "Mixed Veg Curry (1 cup)": {"calories": 130, "protein_g": 4, "carbs_g": 18, "fat_g": 5, "fiber_g": 4},
    "Egg Curry (2 eggs)": {"calories": 250, "protein_g": 15, "carbs_g": 8, "fat_g": 18, "fiber_g": 1},
    "Fish Curry (1 cup)": {"calories": 210, "protein_g": 22, "carbs_g": 6, "fat_g": 11, "fiber_g": 1},
    # Snacks
    "Samosa (1)": {"calories": 262, "protein_g": 4, "carbs_g": 32, "fat_g": 13, "fiber_g": 2},
    "Bhaji/Pakora (2 pieces)": {"calories": 130, "protein_g": 3, "carbs_g": 16, "fat_g": 6, "fiber_g": 2},
    "Pani Puri (6 pieces)": {"calories": 180, "protein_g": 3, "carbs_g": 32, "fat_g": 5, "fiber_g": 2},
    "Bhel Puri (1 plate)": {"calories": 200, "protein_g": 5, "carbs_g": 38, "fat_g": 4, "fiber_g": 3},
    "Dhokla (2 pieces)": {"calories": 120, "protein_g": 5, "carbs_g": 20, "fat_g": 2, "fiber_g": 2},
    "Khakhra (1)": {"calories": 60, "protein_g": 2, "carbs_g": 10, "fat_g": 1.5, "fiber_g": 1},
    "Biscuits Marie (3)": {"calories": 90, "protein_g": 1.5, "carbs_g": 15, "fat_g": 2.5, "fiber_g": 0.5},
    # Sweets
    "Gulab Jamun (1)": {"calories": 150, "protein_g": 2, "carbs_g": 26, "fat_g": 5, "fiber_g": 0.3},
    "Halwa (1/2 cup)": {"calories": 280, "protein_g": 4, "carbs_g": 42, "fat_g": 10, "fiber_g": 1},
    "Kheer (1 cup)": {"calories": 240, "protein_g": 6, "carbs_g": 38, "fat_g": 7, "fiber_g": 0.5},
    "Rasgulla (1)": {"calories": 107, "protein_g": 3, "carbs_g": 20, "fat_g": 2, "fiber_g": 0},
    "Ladoo Besan (1)": {"calories": 180, "protein_g": 3.5, "carbs_g": 24, "fat_g": 8, "fiber_g": 1},
    # Drinks
    "Chai with milk (1 cup)": {"calories": 55, "protein_g": 2, "carbs_g": 8, "fat_g": 2, "fiber_g": 0},
    "Lassi Sweet (1 glass)": {"calories": 190, "protein_g": 6, "carbs_g": 30, "fat_g": 5, "fiber_g": 0},
    "Buttermilk/Chaas (1 glass)": {"calories": 60, "protein_g": 3, "carbs_g": 7, "fat_g": 2, "fiber_g": 0},
    "Mango Lassi (1 glass)": {"calories": 230, "protein_g": 5, "carbs_g": 38, "fat_g": 5, "fiber_g": 1},
}

# ── Auth & sheet helpers ──────────────────────────────────────────────────────

@st.cache_resource
def get_gspread_client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


def get_spreadsheet():
    gc = get_gspread_client()
    return gc.open_by_key(st.secrets["google_sheets"]["spreadsheet_id"])


def get_or_create_worksheet(spreadsheet, title: str, headers: list):
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option="RAW")
        ws.format("1:1", {
            "backgroundColor": {"red": 0.102, "green": 0.180, "blue": 0.133},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "horizontalAlignment": "CENTER",
        })
    return ws


def load_meals_ws():
    sp = get_spreadsheet()
    return get_or_create_worksheet(sp, SHEET_MEALS, MEAL_HEADERS)


def load_daily_ws():
    sp = get_spreadsheet()
    return get_or_create_worksheet(sp, SHEET_DAILY, DAILY_HEADERS)


def _next_id(ws) -> int:
    records = ws.get_all_values()
    if len(records) <= 1:
        return 1
    try:
        ids = [int(r[0]) for r in records[1:] if r[0].isdigit()]
        return max(ids) + 1 if ids else 1
    except Exception:
        return len(records)


def save_meal(data: dict) -> int:
    ws_meals = load_meals_ws()
    meal_id  = _next_id(ws_meals)
    now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_row = [
        meal_id, now,
        data.get("food_name", "Unknown"),
        data.get("serving_size", ""),
        data.get("calories", 0),
        data.get("protein_g", 0),
        data.get("carbs_g", 0),
        data.get("fat_g", 0),
        data.get("fiber_g", 0),
        data.get("sugar_g", 0),
        data.get("health_score", 0),
        data.get("confidence", 0),
        data.get("tips", ""),
        json.dumps(data.get("ingredients", [])),
    ]
    ws_meals.append_row(new_row, value_input_option="USER_ENTERED")
    _refresh_daily_summary()
    return meal_id


def get_all_meals() -> list[dict]:
    ws = load_meals_ws()
    records = ws.get_all_records()
    return records


def get_today_meals() -> list[dict]:
    today = date.today().isoformat()
    return [r for r in get_all_meals() if str(r.get("Logged At", "")).startswith(today)]


def delete_meal(meal_id: int):
    ws = load_meals_ws()
    cell = ws.find(str(meal_id), in_column=1)
    if cell:
        ws.delete_rows(cell.row)
    _refresh_daily_summary()


def _refresh_daily_summary():
    meals = get_all_meals()
    daily: dict = {}
    for m in meals:
        day = str(m.get("Logged At", ""))[:10]
        if not day:
            continue
        if day not in daily:
            daily[day] = {"meals": 0, "cal": 0.0, "prot": 0.0, "carb": 0.0, "fat": 0.0}
        daily[day]["meals"] += 1
        daily[day]["cal"]   += float(m.get("Calories", 0) or 0)
        daily[day]["prot"]  += float(m.get("Protein (g)", 0) or 0)
        daily[day]["carb"]  += float(m.get("Carbs (g)", 0) or 0)
        daily[day]["fat"]   += float(m.get("Fat (g)", 0) or 0)

    ws = load_daily_ws()
    existing_rows = len(ws.get_all_values())
    if existing_rows > 1:
        ws.delete_rows(2, existing_rows)

    rows = []
    for day in sorted(daily.keys(), reverse=True):
        s = daily[day]
        rows.append([
            day, s["meals"],
            round(s["cal"], 1), round(s["prot"], 1),
            round(s["carb"], 1), round(s["fat"], 1),
        ])
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Cal AI – Food Analyzer", page_icon="🥗", layout="centered")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background: #0d0f12; color: #f0ede8; }
h1, h2, h3 { font-family: 'Syne', sans-serif !important; }
.hero-title {
    font-family: 'Syne', sans-serif; font-size: 2.8rem; font-weight: 800;
    background: linear-gradient(135deg, #a8ff78, #78ffd6);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    letter-spacing: -1px; line-height: 1.1; margin-bottom: 0.2rem;
}
.hero-sub { color: #888; font-size: 1rem; font-weight: 300; margin-bottom: 0.5rem; }
.targets-bar {
    background: #111820; border: 1px solid #1e2a38; border-radius: 12px;
    padding: 10px 16px; font-size: 0.82rem; color: #6b8ba4; margin-bottom: 1rem;
    display: flex; gap: 18px; flex-wrap: wrap;
}
.targets-bar span { color: #8ab4c8; font-weight: 500; }
.macro-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 1.5rem 0; }
.macro-card {
    background: #161a20; border: 1px solid #2a2f38; border-radius: 16px;
    padding: 18px 14px; text-align: center; transition: transform 0.2s;
}
.macro-card:hover { transform: translateY(-2px); }
.macro-value { font-family: 'Syne', sans-serif; font-size: 1.7rem; font-weight: 700; line-height: 1; }
.macro-label { font-size: 0.72rem; color: #666; text-transform: uppercase; letter-spacing: 1px; margin-top: 6px; }
.cal-value  { color: #a8ff78; }
.prot-value { color: #78d4ff; }
.carb-value { color: #ffcc78; }
.fat-value  { color: #ff9f78; }
.upload-hint { text-align: center; color: #555; font-size: 0.85rem; margin-top: 0.5rem; }
.food-badge {
    display: inline-block; background: #1e2530; border: 1px solid #2e3a4a;
    border-radius: 50px; padding: 6px 18px; font-family: 'Syne', sans-serif;
    font-size: 1.1rem; font-weight: 600; color: #f0ede8; margin-bottom: 1rem;
}
.ingredient-item {
    background: #161a20; border-left: 3px solid #2a2f38; border-radius: 0 10px 10px 0;
    padding: 10px 16px; margin-bottom: 8px; font-size: 0.9rem; color: #c0bdb8;
}
.conf-bar-bg { background: #1e2530; border-radius: 99px; height: 6px; margin-top: 6px; }
.conf-bar-fill { height: 6px; border-radius: 99px; background: linear-gradient(90deg, #a8ff78, #78ffd6); }
.tip-box {
    background: #111820; border: 1px dashed #2a3545; border-radius: 12px;
    padding: 14px 18px; color: #8a9ab0; font-size: 0.82rem; margin-top: 1rem;
}
.log-row {
    display: flex; justify-content: space-between; align-items: center;
    background: #161a20; border-radius: 10px; padding: 10px 16px;
    margin-bottom: 6px; font-size: 0.88rem;
}
.log-time { color: #555; font-size: 0.75rem; }
.db-badge {
    display: inline-block; background: #0d1a14; border: 1px solid #1a4028;
    border-radius: 8px; padding: 4px 12px; font-size: 0.75rem; color: #34a853; margin-bottom: 1rem;
}
.progress-bar-bg { background: #1e2530; border-radius: 99px; height: 10px; margin: 4px 0 12px 0; }
.progress-bar-fill { height: 10px; border-radius: 99px; transition: width 0.4s; }
.progress-over { background: linear-gradient(90deg, #ff6b6b, #ff4444); }
.section-label { font-size: 0.75rem; color: #555; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 6px; }
.indian-food-card {
    background: #161a20; border: 1px solid #222830; border-radius: 12px;
    padding: 12px 16px; margin-bottom: 8px; cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
}
.indian-food-card:hover { border-color: #a8ff78; background: #1a2018; }
hr { border-color: #1e2530; }
.stButton > button {
    background: linear-gradient(135deg, #a8ff78, #78ffd6) !important;
    color: #0d0f12 !important; font-family: 'Syne', sans-serif !important;
    font-weight: 700 !important; border: none !important; border-radius: 50px !important;
    padding: 0.6rem 2rem !important; font-size: 1rem !important; width: 100%;
}
.stButton > button:hover { opacity: 0.9; }
[data-testid="stFileUploaderDropzone"] {
    background: #161a20 !important; border: 2px dashed #2a3040 !important; border-radius: 16px !important;
}
.edit-box {
    background: #111820; border: 1px solid #a8ff7855; border-radius: 16px;
    padding: 20px; margin: 1rem 0;
}
.edit-box-title { font-family: 'Syne', sans-serif; font-size: 1rem; font-weight: 700; color: #a8ff78; margin-bottom: 12px; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="hero-title">Cal AI</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-sub">Snap your meal → accurate nutrition facts, Indian food ready</div>', unsafe_allow_html=True)

# Show daily targets
st.markdown(f"""
<div class="targets-bar">
  🎯 Daily targets for 80kg / 5'3": &nbsp;
  <span>🔥 {DAILY_CALORIE_TARGET} kcal</span>
  <span>🥩 {PROTEIN_TARGET_G}g protein</span>
  <span>🍞 {CARBS_TARGET_G}g carbs</span>
  <span>🧈 {FAT_TARGET_G}g fat</span>
</div>
""", unsafe_allow_html=True)

sheet_id = st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else "#"
st.markdown(
    f'<div class="db-badge">📊 <a href="{sheet_url}" target="_blank" style="color:#34a853;text-decoration:none;">Google Sheets DB ↗</a></div>',
    unsafe_allow_html=True
)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_analyze, tab_indian, tab_today, tab_history, tab_charts = st.tabs([
    "📸 Analyze", "🇮🇳 Indian Foods", "📅 Today", "🗂️ History", "📊 Charts"
])

# ════════════════════════════════════════════════════════════════════════════════
# IMPROVED ANALYSIS PROMPT
# ════════════════════════════════════════════════════════════════════════════════
VISION_PROMPT = """You are an expert nutritionist and food recognition AI with deep knowledge of Indian and global cuisines.

Analyze this food image carefully and return ONLY a valid JSON object. Be HIGHLY ACCURATE.

Rules:
- Estimate portion size visually (plate size, bowl depth, standard serving norms)
- For Indian foods, use standard ICMR/NIN nutritional values  
- If multiple items are present, sum their nutrition but list each as an ingredient
- Confidence: how sure you are about food identification (0-100)
- Health score: overall nutritional quality considering macros, fiber, processing level (0-100)
- Be specific with food names (e.g., "Butter Chicken with Naan" not "Indian curry")
- Calories must be realistic — cross-check: protein*4 + carbs*4 + fat*9 ≈ total calories

Return EXACTLY this JSON (no markdown, no extra text):
{
  "food_name": "Specific dish name",
  "confidence": 82,
  "serving_size": "1 plate (~300g)",
  "calories": 520,
  "protein_g": 28,
  "carbs_g": 45,
  "fat_g": 18,
  "fiber_g": 5,
  "sugar_g": 8,
  "ingredients": [
    {"name": "Ingredient name", "calories": 165, "amount": "150g", "protein_g": 10, "carbs_g": 0, "fat_g": 7}
  ],
  "health_score": 72,
  "tips": "One specific, actionable nutritionist tip relevant to this meal."
}"""

TEXT_PROMPT = """You are an expert nutritionist with deep knowledge of Indian and global cuisines.

Analyze this meal description and return ONLY valid JSON. Be HIGHLY ACCURATE using standard nutrition databases (ICMR/NIN for Indian foods, USDA for others).

Rules:
- Use standard serving sizes unless specified
- For Indian foods: use traditional recipes (not restaurant versions which have more oil/butter)
- Verify calorie math: protein*4 + carbs*4 + fat*9 should approximately equal total calories
- Health score considers: fiber content, protein quality, processing level, nutrient density (0-100)

Meal to analyze: "{meal_description}"

Return EXACTLY this JSON (no markdown, no extra text):
{{
  "food_name": "Specific dish name",
  "confidence": 88,
  "serving_size": "estimated portion",
  "calories": 520,
  "protein_g": 28,
  "carbs_g": 45,
  "fat_g": 18,
  "fiber_g": 5,
  "sugar_g": 8,
  "ingredients": [
    {{"name": "Ingredient", "calories": 165, "amount": "150g", "protein_g": 10, "carbs_g": 0, "fat_g": 7}}
  ],
  "health_score": 72,
  "tips": "One specific, actionable nutritionist tip relevant to this meal."
}}"""

# ════════════════════════════════════════════════════════════════════════════════
# Helper: render macro progress bar
# ════════════════════════════════════════════════════════════════════════════════
def render_progress(label, current, target, color):
    pct = min(current / target * 100, 100) if target > 0 else 0
    over = current > target
    bar_class = "progress-over" if over else ""
    bar_style = f"background: {color};" if not over else ""
    st.markdown(f"""
    <div style="margin-bottom:4px">
      <div style="display:flex;justify-content:space-between;font-size:0.8rem">
        <span style="color:#888">{label}</span>
        <span style="color:{'#ff6b6b' if over else '#aaa'}">{current:.0f} / {target} {'⚠️ over' if over else ''}</span>
      </div>
      <div class="progress-bar-bg">
        <div class="progress-bar-fill {bar_class}" style="width:{pct}%;{bar_style}"></div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 – Analyze
# ════════════════════════════════════════════════════════════════════════════════
with tab_analyze:
    if "result" not in st.session_state:
        st.session_state.result = None
    if "pending_save" not in st.session_state:
        st.session_state.pending_save = None

    uploaded_file = st.file_uploader(
        "Upload a food photo", type=["jpg", "jpeg", "png", "webp"],
        label_visibility="collapsed"
    )
    st.markdown('<div class="upload-hint">JPG · PNG · WEBP supported</div>', unsafe_allow_html=True)

    text_input = st.text_area(
        "Or describe your meal in text",
        height=100,
        placeholder="e.g., 2 rotis with dal makhani and a katori of sabzi"
    )

    analyze_enabled = uploaded_file is not None or text_input.strip()

    if analyze_enabled:
        if uploaded_file:
            image = Image.open(uploaded_file)
            st.image(image, use_container_width=True, caption="")

        if st.button("🔍 Analyze Meal"):
            with st.spinner("Analyzing your meal with high accuracy..."):
                client = anthropic.Anthropic(api_key=st.secrets["anthropic"]["api_key"])

                if uploaded_file:
                    buf = io.BytesIO()
                    fmt = image.format or "JPEG"
                    image.save(buf, format=fmt)
                    img_b64 = base64.standard_b64encode(buf.getvalue()).decode()
                    media_type = f"image/{fmt.lower()}"

                    prompt = VISION_PROMPT
                    if text_input.strip():
                        prompt += f"\n\nAdditional context from user: {text_input.strip()}"

                    content = [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                        {"type": "text", "text": prompt}
                    ]
                    model = "claude-haiku-4-5-20251001"
                else:
                    prompt = TEXT_PROMPT.format(meal_description=text_input.strip())
                    content = [{"type": "text", "text": prompt}]
                    model = "claude-sonnet-4-6"

                response = client.messages.create(
                    model=model,
                    max_tokens=1500,
                    messages=[{"role": "user", "content": content}]
                )

                raw = response.content[0].text.strip()
                # Strip markdown code fences if present
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()
                data = json.loads(raw)

            st.session_state.pending_save = data
            st.session_state.result = None  # clear old result

    # ── Editable review before saving ────────────────────────────────────────
    if st.session_state.pending_save and not st.session_state.result:
        d = st.session_state.pending_save
        st.markdown("---")
        st.markdown(f'<div class="food-badge">🍽️ {d.get("food_name","Unknown Food")}</div>', unsafe_allow_html=True)

        conf = d.get("confidence", 0)
        st.markdown(f"""
        <div style="margin-bottom:1rem">
            <div style="font-size:0.78rem;color:#666;text-transform:uppercase;letter-spacing:1px">AI Confidence · {conf}%</div>
            <div class="conf-bar-bg"><div class="conf-bar-fill" style="width:{conf}%"></div></div>
        </div>""", unsafe_allow_html=True)

        st.markdown('<div class="edit-box">', unsafe_allow_html=True)
        st.markdown('<div class="edit-box-title">✏️ Review & Adjust Values Before Saving</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            food_name  = st.text_input("Food Name", value=d.get("food_name", ""))
            calories   = st.number_input("Calories (kcal)", value=int(d.get("calories", 0)), min_value=0, step=5)
            protein    = st.number_input("Protein (g)", value=float(d.get("protein_g", 0)), min_value=0.0, step=0.5)
            carbs      = st.number_input("Carbs (g)", value=float(d.get("carbs_g", 0)), min_value=0.0, step=0.5)
        with col2:
            serving    = st.text_input("Serving Size", value=d.get("serving_size", ""))
            fat        = st.number_input("Fat (g)", value=float(d.get("fat_g", 0)), min_value=0.0, step=0.5)
            fiber      = st.number_input("Fiber (g)", value=float(d.get("fiber_g", 0)), min_value=0.0, step=0.5)
            sugar      = st.number_input("Sugar (g)", value=float(d.get("sugar_g", 0)), min_value=0.0, step=0.5)

        # Show macro check
        macro_cal = protein * 4 + carbs * 4 + fat * 9
        diff = abs(calories - macro_cal)
        if diff > 30:
            st.warning(f"⚠️ Macro check: Protein+Carbs+Fat = {macro_cal:.0f} kcal vs {calories} entered (diff: {diff:.0f}). Consider adjusting.")
        else:
            st.success(f"✅ Macro check: Calculated {macro_cal:.0f} kcal ≈ {calories} entered — looks good!")

        st.markdown('</div>', unsafe_allow_html=True)

        if d.get("tips"):
            st.markdown(f'<div class="tip-box">💡 {d["tips"]}</div>', unsafe_allow_html=True)

        col_save, col_discard = st.columns(2)
        with col_save:
            if st.button("💾 Save to Log"):
                d.update({
                    "food_name": food_name,
                    "serving_size": serving,
                    "calories": calories,
                    "protein_g": protein,
                    "carbs_g": carbs,
                    "fat_g": fat,
                    "fiber_g": fiber,
                    "sugar_g": sugar,
                })
                with st.spinner("Saving to Google Sheets..."):
                    meal_id = save_meal(d)
                    d["_db_id"] = meal_id
                    st.session_state.result = d
                    st.session_state.pending_save = None
                st.success(f"✅ Saved to Google Sheets (Row #{meal_id})")
                st.rerun()
        with col_discard:
            if st.button("🗑️ Discard"):
                st.session_state.pending_save = None
                st.rerun()

    # ── Show saved result ─────────────────────────────────────────────────────
    if st.session_state.result:
        d = st.session_state.result
        st.markdown("---")
        st.markdown(f'<div class="food-badge">✅ Logged: {d.get("food_name","Unknown Food")}</div>', unsafe_allow_html=True)

        st.markdown(f"""
        <div class="macro-grid">
            <div class="macro-card"><div class="macro-value cal-value">{d.get('calories',0)}</div><div class="macro-label">Calories</div></div>
            <div class="macro-card"><div class="macro-value prot-value">{d.get('protein_g',0)}g</div><div class="macro-label">Protein</div></div>
            <div class="macro-card"><div class="macro-value carb-value">{d.get('carbs_g',0)}g</div><div class="macro-label">Carbs</div></div>
            <div class="macro-card"><div class="macro-value fat-value">{d.get('fat_g',0)}g</div><div class="macro-label">Fat</div></div>
        </div>""", unsafe_allow_html=True)

        st.markdown("**Detected Ingredients**")
        for ing in d.get("ingredients", []):
            st.markdown(
                f'<div class="ingredient-item">🥄 <b>{ing["name"]}</b> · {ing.get("amount","—")} · {ing.get("calories","—")} kcal</div>',
                unsafe_allow_html=True
            )

# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 – Indian Foods Quick Log
# ════════════════════════════════════════════════════════════════════════════════
with tab_indian:
    st.markdown("### 🇮🇳 Indian Food Quick Log")
    st.caption("Pre-calibrated nutritional values from ICMR/NIN database. Click to add to today's log.")

    search_query = st.text_input("🔍 Search Indian foods", placeholder="e.g., biryani, roti, dal...")

    categories = {
        "🌅 Breakfast": ["Idli (1 piece)", "Dosa (1 plain)", "Masala Dosa", "Poha (1 cup)", "Upma (1 cup)",
                          "Paratha (1 plain)", "Aloo Paratha", "Besan Chilla (1)", "Medu Vada (1)", "Pongal (1 cup)"],
        "🍚 Rice Dishes": ["Steamed Rice (1 cup cooked)", "Jeera Rice (1 cup)", "Biryani Chicken (1 plate ~350g)",
                            "Biryani Veg (1 plate ~350g)", "Curd Rice (1 cup)", "Lemon Rice (1 cup)", "Sambar Rice (1 cup)"],
        "🫓 Breads": ["Roti/Chapati (1)", "Puri (1)", "Naan (1)", "Paratha (1 plain)", "Aloo Paratha"],
        "🍛 Curries & Dals": ["Dal Tadka (1 cup)", "Dal Makhani (1 cup)", "Chana Masala (1 cup)", "Rajma (1 cup)",
                               "Paneer Butter Masala (1 cup)", "Palak Paneer (1 cup)", "Butter Chicken (1 cup)",
                               "Chicken Tikka Masala (1 cup)", "Aloo Sabzi (1 cup)", "Mixed Veg Curry (1 cup)",
                               "Egg Curry (2 eggs)", "Fish Curry (1 cup)"],
        "🥟 Snacks": ["Samosa (1)", "Bhaji/Pakora (2 pieces)", "Pani Puri (6 pieces)", "Bhel Puri (1 plate)",
                       "Dhokla (2 pieces)", "Khakhra (1)", "Biscuits Marie (3)"],
        "🍮 Sweets": ["Gulab Jamun (1)", "Halwa (1/2 cup)", "Kheer (1 cup)", "Rasgulla (1)", "Ladoo Besan (1)"],
        "🥛 Drinks": ["Chai with milk (1 cup)", "Lassi Sweet (1 glass)", "Buttermilk/Chaas (1 glass)", "Mango Lassi (1 glass)"],
    }

    # Filter if search
    if search_query.strip():
        filtered = {k: v for k, v in INDIAN_FOOD_DB.items()
                    if search_query.lower() in k.lower()}
        if filtered:
            st.markdown(f"**Found {len(filtered)} items:**")
            for food_name, nutrients in filtered.items():
                col_info, col_btn = st.columns([4, 1])
                with col_info:
                    st.markdown(
                        f'<div class="ingredient-item"><b>{food_name}</b> · '
                        f'🔥{nutrients["calories"]} kcal · 🥩{nutrients["protein_g"]}g · '
                        f'🍞{nutrients["carbs_g"]}g · 🧈{nutrients["fat_g"]}g</div>',
                        unsafe_allow_html=True
                    )
                with col_btn:
                    if st.button("➕ Add", key=f"search_{food_name}"):
                        data = {
                            "food_name": food_name,
                            "serving_size": "Standard serving",
                            "calories": nutrients["calories"],
                            "protein_g": nutrients["protein_g"],
                            "carbs_g": nutrients["carbs_g"],
                            "fat_g": nutrients["fat_g"],
                            "fiber_g": nutrients.get("fiber_g", 0),
                            "sugar_g": 0,
                            "health_score": 70,
                            "confidence": 99,
                            "tips": "From ICMR/NIN Indian nutrition database.",
                            "ingredients": [{"name": food_name, "calories": nutrients["calories"], "amount": "1 serving"}]
                        }
                        with st.spinner("Saving..."):
                            meal_id = save_meal(data)
                        st.success(f"✅ Added {food_name} (Row #{meal_id})")
                        st.rerun()
        else:
            st.info("No matching foods found in the database.")
    else:
        for cat_idx, (cat_name, food_list) in enumerate(categories.items()):
            with st.expander(cat_name):
                for food_name in food_list:
                    if food_name not in INDIAN_FOOD_DB:
                        continue
                    nutrients = INDIAN_FOOD_DB[food_name]
                    # Use cat_idx + food_name to guarantee uniqueness across categories
                    safe_key = f"c{cat_idx}_{food_name}"
                    col_info, col_qty, col_btn = st.columns([3, 1, 1])
                    with col_info:
                        st.markdown(
                            f'<div style="padding:6px 0"><b>{food_name}</b><br>'
                            f'<span style="color:#666;font-size:0.8rem">'
                            f'🔥{nutrients["calories"]} · 🥩{nutrients["protein_g"]}g · '
                            f'🍞{nutrients["carbs_g"]}g · 🧈{nutrients["fat_g"]}g</span></div>',
                            unsafe_allow_html=True
                        )
                    with col_qty:
                        qty = st.number_input("Qty", value=1.0, min_value=0.5, step=0.5,
                                              key=f"qty_{safe_key}", label_visibility="collapsed")
                    with col_btn:
                        if st.button("➕", key=f"add_{safe_key}"):
                            data = {
                                "food_name": f"{food_name}" + (f" ×{qty}" if qty != 1 else ""),
                                "serving_size": f"{qty} × standard serving",
                                "calories": round(nutrients["calories"] * qty),
                                "protein_g": round(nutrients["protein_g"] * qty, 1),
                                "carbs_g": round(nutrients["carbs_g"] * qty, 1),
                                "fat_g": round(nutrients["fat_g"] * qty, 1),
                                "fiber_g": round(nutrients.get("fiber_g", 0) * qty, 1),
                                "sugar_g": 0,
                                "health_score": 70,
                                "confidence": 99,
                                "tips": "From ICMR/NIN Indian nutrition database.",
                                "ingredients": [{"name": food_name, "calories": round(nutrients["calories"] * qty), "amount": f"{qty} serving"}]
                            }
                            with st.spinner("Saving..."):
                                meal_id = save_meal(data)
                            st.success(f"✅ Added! (Row #{meal_id})")
                            st.rerun()

# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 – Today
# ════════════════════════════════════════════════════════════════════════════════
with tab_today:
    st.markdown(f"### {date.today().strftime('%A, %B %d')}")
    with st.spinner("Loading today's meals..."):
        today_meals = get_today_meals()

    if today_meals:
        total_cal  = sum(float(m.get("Calories", 0) or 0) for m in today_meals)
        total_prot = sum(float(m.get("Protein (g)", 0) or 0) for m in today_meals)
        total_carb = sum(float(m.get("Carbs (g)", 0) or 0) for m in today_meals)
        total_fat  = sum(float(m.get("Fat (g)", 0) or 0) for m in today_meals)
        total_fiber= sum(float(m.get("Fiber (g)", 0) or 0) for m in today_meals)

        st.markdown(f"""
        <div class="macro-grid">
            <div class="macro-card"><div class="macro-value cal-value">{int(total_cal)}</div><div class="macro-label">Calories</div></div>
            <div class="macro-card"><div class="macro-value prot-value">{int(total_prot)}g</div><div class="macro-label">Protein</div></div>
            <div class="macro-card"><div class="macro-value carb-value">{int(total_carb)}g</div><div class="macro-label">Carbs</div></div>
            <div class="macro-card"><div class="macro-value fat-value">{int(total_fat)}g</div><div class="macro-label">Fat</div></div>
        </div>""", unsafe_allow_html=True)

        # Progress toward targets
        st.markdown("**Progress toward daily targets:**")
        render_progress("🔥 Calories", total_cal, DAILY_CALORIE_TARGET, "#a8ff78")
        render_progress("🥩 Protein", total_prot, PROTEIN_TARGET_G, "#78d4ff")
        render_progress("🍞 Carbs", total_carb, CARBS_TARGET_G, "#ffcc78")
        render_progress("🧈 Fat", total_fat, FAT_TARGET_G, "#ff9f78")

        remaining_cal = DAILY_CALORIE_TARGET - total_cal
        if remaining_cal > 0:
            st.info(f"🍽️ You have **{int(remaining_cal)} kcal** remaining today. Fiber: {total_fiber:.0f}g (target: 25g)")
        else:
            st.warning(f"⚠️ You've exceeded your calorie target by **{int(-remaining_cal)} kcal** today.")

        st.caption(f"{len(today_meals)} meal(s) logged today")
        st.markdown("---")

        for meal in today_meals:
            t = str(meal.get("Logged At", ""))[11:16]
            col_info, col_del = st.columns([5, 1])
            with col_info:
                st.markdown(
                    f'<div class="log-row">'
                    f'<span><b>{meal["Food Name"]}</b> <span class="log-time">{t}</span></span>'
                    f'<span class="cal-value" style="font-family:Syne,sans-serif;font-weight:700">{int(float(meal["Calories"] or 0))} kcal</span>'
                    f'</div>', unsafe_allow_html=True
                )
            with col_del:
                if st.button("🗑️", key=f"del_{meal['ID']}"):
                    with st.spinner("Deleting..."):
                        delete_meal(int(meal["ID"]))
                    st.rerun()
    else:
        st.info("No meals logged today. Head to **Analyze** or **Indian Foods** to log your first meal!")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 – History
# ════════════════════════════════════════════════════════════════════════════════
with tab_history:
    with st.spinner("Loading history..."):
        all_meals = get_all_meals()

    if not all_meals:
        st.info("No meal history yet.")
    else:
        from itertools import groupby
        keyfn = lambda m: str(m.get("Logged At", ""))[:10]
        sorted_meals = sorted(all_meals, key=keyfn, reverse=True)

        for day, group in groupby(sorted_meals, key=keyfn):
            day_meals = list(group)
            total_cal = int(sum(float(m.get("Calories", 0) or 0) for m in day_meals))
            pct_target = round(total_cal / DAILY_CALORIE_TARGET * 100)
            try:
                day_label = datetime.fromisoformat(day).strftime("%A, %B %d %Y")
            except ValueError:
                day_label = day

            indicator = "✅" if 80 <= pct_target <= 110 else ("⚠️" if pct_target > 110 else "📉")

            with st.expander(f"{indicator} {day_label}  ·  {total_cal} kcal ({pct_target}% of target)  ·  {len(day_meals)} meal(s)"):
                for meal in day_meals:
                    t = str(meal.get("Logged At", ""))[11:16]
                    col_i, col_m, col_d = st.columns([3, 4, 1])
                    with col_i:
                        st.markdown(f"**{meal['Food Name']}**  \n🕐 {t}")
                    with col_m:
                        st.markdown(
                            f"🔥 {int(float(meal.get('Calories',0) or 0))} kcal &nbsp;·&nbsp; "
                            f"🥩 {int(float(meal.get('Protein (g)',0) or 0))}g &nbsp;·&nbsp; "
                            f"🍞 {int(float(meal.get('Carbs (g)',0) or 0))}g &nbsp;·&nbsp; "
                            f"🧈 {int(float(meal.get('Fat (g)',0) or 0))}g",
                            unsafe_allow_html=True
                        )
                    with col_d:
                        if st.button("🗑️", key=f"hist_{meal['ID']}"):
                            with st.spinner("Deleting..."):
                                delete_meal(int(meal["ID"]))
                            st.rerun()
                    st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 5 – Charts
# ════════════════════════════════════════════════════════════════════════════════
with tab_charts:
    st.markdown("### 📊 Nutrition Analytics")
    st.caption(f"Daily targets: {DAILY_CALORIE_TARGET} kcal · {PROTEIN_TARGET_G}g protein · {CARBS_TARGET_G}g carbs · {FAT_TARGET_G}g fat")

    with st.spinner("Loading data for charts..."):
        all_meals_chart = get_all_meals()

    if not all_meals_chart:
        st.info("No data yet. Log some meals to see charts!")
    else:
        # Aggregate by day
        daily_data: dict = {}
        for m in all_meals_chart:
            day = str(m.get("Logged At", ""))[:10]
            if not day:
                continue
            if day not in daily_data:
                daily_data[day] = {"cal": 0.0, "prot": 0.0, "carb": 0.0, "fat": 0.0, "fiber": 0.0, "meals": 0}
            daily_data[day]["cal"]   += float(m.get("Calories", 0) or 0)
            daily_data[day]["prot"]  += float(m.get("Protein (g)", 0) or 0)
            daily_data[day]["carb"]  += float(m.get("Carbs (g)", 0) or 0)
            daily_data[day]["fat"]   += float(m.get("Fat (g)", 0) or 0)
            daily_data[day]["fiber"] += float(m.get("Fiber (g)", 0) or 0)
            daily_data[day]["meals"] += 1

        days_sorted = sorted(daily_data.keys())[-14:]  # last 14 days
        labels = [d[5:] for d in days_sorted]  # MM-DD format

        import streamlit as st

        # ── Chart 1: Calories vs Target ───────────────────────────────────────
        st.markdown("#### 🔥 Daily Calories vs Target")
        cal_vals = [daily_data[d]["cal"] for d in days_sorted]

        # Build simple HTML bar chart
        max_val = max(max(cal_vals) if cal_vals else 1, DAILY_CALORIE_TARGET) * 1.15
        bars_html = '<div style="display:flex;align-items:flex-end;gap:6px;height:180px;margin-bottom:8px;background:#0d1117;border-radius:12px;padding:16px 12px 28px 12px;position:relative;">'

        # Target line
        target_pct = DAILY_CALORIE_TARGET / max_val * 100
        bars_html += f'<div style="position:absolute;left:12px;right:12px;bottom:{target_pct:.1f}%;border-top:2px dashed #a8ff7888;z-index:5;"><span style="font-size:0.65rem;color:#a8ff78;position:absolute;right:4px;top:-14px">{DAILY_CALORIE_TARGET}</span></div>'

        for i, (lbl, val) in enumerate(zip(labels, cal_vals)):
            pct = val / max_val * 100
            color = "#a8ff78" if val <= DAILY_CALORIE_TARGET * 1.05 else "#ff6b6b"
            bars_html += f'''
            <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:2px">
                <span style="font-size:0.6rem;color:#666;margin-bottom:2px">{int(val)}</span>
                <div style="width:100%;height:{pct:.1f}%;background:{color};border-radius:4px 4px 0 0;min-height:3px"></div>
                <span style="font-size:0.6rem;color:#555;margin-top:4px">{lbl}</span>
            </div>'''
        bars_html += '</div>'
        st.markdown(bars_html, unsafe_allow_html=True)

        # ── Chart 2: Macros breakdown ─────────────────────────────────────────
        st.markdown("#### 🥗 Macro Breakdown (last 7 days)")
        last7 = days_sorted[-7:] if len(days_sorted) >= 7 else days_sorted
        for day in last7:
            d = daily_data[day]
            total = d["prot"] + d["carb"] + d["fat"]
            if total < 1:
                continue
            p_pct = d["prot"] * 4 / (d["cal"] or 1) * 100
            c_pct = d["carb"] * 4 / (d["cal"] or 1) * 100
            f_pct = d["fat"] * 9 / (d["cal"] or 1) * 100

            try:
                day_fmt = datetime.fromisoformat(day).strftime("%b %d")
            except:
                day_fmt = day[5:]

            st.markdown(f"""
            <div style="margin-bottom:10px">
              <div style="display:flex;justify-content:space-between;font-size:0.78rem;color:#888;margin-bottom:3px">
                <span>{day_fmt}</span>
                <span>🔥{int(d['cal'])} kcal</span>
              </div>
              <div style="display:flex;height:14px;border-radius:8px;overflow:hidden;gap:2px">
                <div style="width:{p_pct:.1f}%;background:#78d4ff;border-radius:8px 0 0 8px"></div>
                <div style="width:{c_pct:.1f}%;background:#ffcc78"></div>
                <div style="width:{f_pct:.1f}%;background:#ff9f78;border-radius:0 8px 8px 0"></div>
              </div>
              <div style="display:flex;gap:12px;font-size:0.7rem;color:#555;margin-top:3px">
                <span style="color:#78d4ff">P {d['prot']:.0f}g</span>
                <span style="color:#ffcc78">C {d['carb']:.0f}g</span>
                <span style="color:#ff9f78">F {d['fat']:.0f}g</span>
                <span style="color:#a0b09a">Fiber {d['fiber']:.0f}g</span>
              </div>
            </div>""", unsafe_allow_html=True)

        # ── Chart 3: 7-day averages vs targets ───────────────────────────────
        st.markdown("#### 📈 7-Day Averages vs Targets")
        if last7:
            avg_cal  = sum(daily_data[d]["cal"]  for d in last7) / len(last7)
            avg_prot = sum(daily_data[d]["prot"] for d in last7) / len(last7)
            avg_carb = sum(daily_data[d]["carb"] for d in last7) / len(last7)
            avg_fat  = sum(daily_data[d]["fat"]  for d in last7) / len(last7)

            metrics = [
                ("🔥 Calories", avg_cal, DAILY_CALORIE_TARGET, "#a8ff78"),
                ("🥩 Protein",  avg_prot, PROTEIN_TARGET_G, "#78d4ff"),
                ("🍞 Carbs",    avg_carb, CARBS_TARGET_G, "#ffcc78"),
                ("🧈 Fat",      avg_fat, FAT_TARGET_G, "#ff9f78"),
            ]
            for label, avg, target, color in metrics:
                pct = min(avg / target * 100, 130) if target > 0 else 0
                status = "✅" if 80 <= avg/target*100 <= 110 else ("⬆️" if avg > target else "⬇️")
                st.markdown(f"""
                <div style="margin-bottom:12px">
                  <div style="display:flex;justify-content:space-between;font-size:0.82rem;margin-bottom:4px">
                    <span style="color:#aaa">{label}</span>
                    <span style="color:#ddd">{status} avg {avg:.0f} / target {target}</span>
                  </div>
                  <div class="progress-bar-bg">
                    <div style="width:{min(pct,100):.1f}%;height:10px;border-radius:99px;background:{color};{"opacity:0.6" if pct>100 else ""}"></div>
                  </div>
                </div>""", unsafe_allow_html=True)

        # ── Chart 4: Calorie trend sparkline ──────────────────────────────────
        st.markdown("#### 📉 Calorie Trend")
        if len(days_sorted) >= 2:
            all_cal = [daily_data[d]["cal"] for d in days_sorted]
            max_c = max(all_cal) * 1.2
            min_c = min(all_cal) * 0.8
            w, h = 560, 100
            points = []
            for i, v in enumerate(all_cal):
                x = i / (len(all_cal) - 1) * (w - 20) + 10
                y = h - ((v - min_c) / (max_c - min_c) * (h - 20) + 10)
                points.append(f"{x:.1f},{y:.1f}")
            polyline = " ".join(points)
            target_y = h - ((DAILY_CALORIE_TARGET - min_c) / (max_c - min_c) * (h - 20) + 10)

            st.markdown(f"""
            <div style="background:#0d1117;border-radius:12px;padding:12px;overflow:hidden">
              <svg viewBox="0 0 {w} {h}" style="width:100%;height:auto">
                <line x1="0" y1="{target_y:.1f}" x2="{w}" y2="{target_y:.1f}" stroke="#a8ff7855" stroke-width="1.5" stroke-dasharray="6,4"/>
                <polyline points="{polyline}" fill="none" stroke="#78ffd6" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
                {''.join(f'<circle cx="{p.split(",")[0]}" cy="{p.split(",")[1]}" r="4" fill="#a8ff78"/>' for p in points)}
              </svg>
              <div style="display:flex;justify-content:space-between;font-size:0.68rem;color:#444;margin-top:4px">
                <span>{days_sorted[0][5:]}</span><span style="color:#a8ff7888">─ target</span><span>{days_sorted[-1][5:]}</span>
              </div>
            </div>""", unsafe_allow_html=True)

        # ── Insight box ───────────────────────────────────────────────────────
        if last7:
            days_over  = sum(1 for d in last7 if daily_data[d]["cal"] > DAILY_CALORIE_TARGET * 1.05)
            days_under = sum(1 for d in last7 if daily_data[d]["cal"] < DAILY_CALORIE_TARGET * 0.75)
            avg_fiber  = sum(daily_data[d]["fiber"] for d in last7) / len(last7)
            low_prot_days = sum(1 for d in last7 if daily_data[d]["prot"] < PROTEIN_TARGET_G * 0.7)

            insights = []
            if days_over:
                insights.append(f"⚠️ Exceeded calorie target on **{days_over} of last {len(last7)} days**. Watch portion sizes!")
            if days_under:
                insights.append(f"📉 Under 75% of calorie target on **{days_under} day(s)** — risk of metabolism slowdown.")
            if avg_fiber < 20:
                insights.append(f"🌾 Average fiber is only **{avg_fiber:.1f}g/day** — aim for 25g+. Add dal, vegetables, whole grains.")
            if low_prot_days:
                insights.append(f"💪 Protein was low (<70% target) on **{low_prot_days} day(s)**. Add paneer, dal, eggs or chicken.")
            if not insights:
                insights.append("✅ Great work! Your nutrition is well-balanced this week.")

            st.markdown('<div class="tip-box"><b>🧠 Weekly Insights</b><br>' + '<br>'.join(insights) + '</div>', unsafe_allow_html=True)