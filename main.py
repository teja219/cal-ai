import streamlit as st
import anthropic
import base64
import json
import os
from datetime import datetime, date
from PIL import Image
import io

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

# ── Auth & sheet helpers ──────────────────────────────────────────────────────

@st.cache_resource
def get_gspread_client():
    """Authenticate using service account credentials from st.secrets."""
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
        # Bold + colour the header row
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
    if len(records) <= 1:           # only header or empty
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
    records = ws.get_all_records()   # list of dicts keyed by header
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
    # Clear all rows below header
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
.hero-sub { color: #888; font-size: 1rem; font-weight: 300; margin-bottom: 1rem; }
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
    padding: 14px 18px; color: #8a9ab0; font-size: 0.82rem; margin-top: 1.5rem;
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
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="hero-title">Cal AI</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-sub">Snap your meal → get instant nutrition facts</div>', unsafe_allow_html=True)

sheet_id = st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else "#"
st.markdown(
    f'<div class="db-badge">📊 <a href="{sheet_url}" target="_blank" style="color:#34a853;text-decoration:none;">Google Sheets DB ↗</a></div>',
    unsafe_allow_html=True
)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_analyze, tab_today, tab_history = st.tabs(["📸 Analyze", "📅 Today", "🗂️ History"])

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 – Analyze
# ════════════════════════════════════════════════════════════════════════════════
with tab_analyze:
    if "result" not in st.session_state:
        st.session_state.result = None

    uploaded_file = st.file_uploader(
        "Upload a food photo", type=["jpg", "jpeg", "png", "webp"],
        label_visibility="collapsed"
    )
    st.markdown('<div class="upload-hint">JPG · PNG · WEBP supported</div>', unsafe_allow_html=True)

    if uploaded_file:
        image = Image.open(uploaded_file)
        st.image(image, use_container_width=True, caption="")

        if st.button("🔍 Analyze Meal"):
            with st.spinner("Analyzing your meal..."):
                buf = io.BytesIO()
                fmt = image.format or "JPEG"
                image.save(buf, format=fmt)
                img_b64 = base64.standard_b64encode(buf.getvalue()).decode()
                media_type = f"image/{fmt.lower()}"

                client = anthropic.Anthropic(api_key=st.secrets["anthropic"]["api_key"])
                prompt = """You are a professional nutritionist and food recognition AI.
Analyze the food in this image and return ONLY a valid JSON object (no markdown, no extra text):

{
  "food_name": "Name of the dish",
  "confidence": 85,
  "calories": 520,
  "protein_g": 28,
  "carbs_g": 45,
  "fat_g": 18,
  "fiber_g": 5,
  "sugar_g": 8,
  "serving_size": "1 plate (~350g)",
  "ingredients": [
    {"name": "Chicken breast", "calories": 165, "amount": "150g"},
    {"name": "Brown rice", "calories": 215, "amount": "120g"}
  ],
  "health_score": 72,
  "tips": "Short nutritionist advice."
}
confidence and health_score are 0-100."""

                response = client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=1000,
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                        {"type": "text", "text": prompt}
                    ]}]
                )

                raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(raw)

            with st.spinner("Saving to Google Sheets..."):
                meal_id = save_meal(data)
                data["_db_id"] = meal_id
                st.session_state.result = data
                st.success(f"✅ Saved to Google Sheets (Row #{meal_id})")

    if st.session_state.result:
        d = st.session_state.result
        st.markdown("---")
        st.markdown(f'<div class="food-badge">🍽️ {d.get("food_name","Unknown Food")}</div>', unsafe_allow_html=True)
        st.caption(f'Serving: {d.get("serving_size","—")}')

        st.markdown(f"""
        <div class="macro-grid">
            <div class="macro-card"><div class="macro-value cal-value">{d.get('calories',0)}</div><div class="macro-label">Calories</div></div>
            <div class="macro-card"><div class="macro-value prot-value">{d.get('protein_g',0)}g</div><div class="macro-label">Protein</div></div>
            <div class="macro-card"><div class="macro-value carb-value">{d.get('carbs_g',0)}g</div><div class="macro-label">Carbs</div></div>
            <div class="macro-card"><div class="macro-value fat-value">{d.get('fat_g',0)}g</div><div class="macro-label">Fat</div></div>
        </div>""", unsafe_allow_html=True)

        col1, col2, col3 = st.columns(3)
        col1.metric("Fiber",        f"{d.get('fiber_g','—')}g")
        col2.metric("Sugar",        f"{d.get('sugar_g','—')}g")
        col3.metric("Health Score", f"{d.get('health_score','—')}/100")

        conf = d.get("confidence", 0)
        st.markdown(f"""
        <div style="margin-top:1rem">
            <div style="font-size:0.78rem;color:#666;text-transform:uppercase;letter-spacing:1px">AI Confidence · {conf}%</div>
            <div class="conf-bar-bg"><div class="conf-bar-fill" style="width:{conf}%"></div></div>
        </div>""", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("**Detected Ingredients**")
        for ing in d.get("ingredients", []):
            st.markdown(
                f'<div class="ingredient-item">🥄 <b>{ing["name"]}</b> · {ing.get("amount","—")} · {ing.get("calories","—")} kcal</div>',
                unsafe_allow_html=True
            )
        if d.get("tips"):
            st.markdown(f'<div class="tip-box">💡 {d["tips"]}</div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 – Today
# ════════════════════════════════════════════════════════════════════════════════
with tab_today:
    st.markdown(f"### {date.today().strftime('%A, %B %d')}")
    with st.spinner("Loading today's meals..."):
        today_meals = get_today_meals()

    if today_meals:
        total_cal  = int(sum(float(m.get("Calories", 0) or 0) for m in today_meals))
        total_prot = int(sum(float(m.get("Protein (g)", 0) or 0) for m in today_meals))
        total_carb = int(sum(float(m.get("Carbs (g)", 0) or 0) for m in today_meals))
        total_fat  = int(sum(float(m.get("Fat (g)", 0) or 0) for m in today_meals))

        st.markdown(f"""
        <div class="macro-grid">
            <div class="macro-card"><div class="macro-value cal-value">{total_cal}</div><div class="macro-label">Calories</div></div>
            <div class="macro-card"><div class="macro-value prot-value">{total_prot}g</div><div class="macro-label">Protein</div></div>
            <div class="macro-card"><div class="macro-value carb-value">{total_carb}g</div><div class="macro-label">Carbs</div></div>
            <div class="macro-card"><div class="macro-value fat-value">{total_fat}g</div><div class="macro-label">Fat</div></div>
        </div>""", unsafe_allow_html=True)
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
        st.info("No meals logged today. Head to **Analyze** to snap your first meal!")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 – History
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
            try:
                day_label = datetime.fromisoformat(day).strftime("%A, %B %d %Y")
            except ValueError:
                day_label = day

            with st.expander(f"📅 {day_label}  ·  {total_cal} kcal  ·  {len(day_meals)} meal(s)"):
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