#!/usr/bin/env python3
"""
מוניטור דירות — יד2 + קומו
בוט טלגרם עם Supabase DB ופילטרים דינמיים.

לוח זמנים:
  05:30–23:30  → בדיקה כל 15 דקות
  23:30–05:30  → בדיקה ב-23:30 ושוב ב-05:30

פקודות בוט:
  /status           — פילטרים נוכחיים
  /filters          — תפריט שינוי פילטרים
  /seen             — חיפוש דירות שנסרקו
  /setprice 5500    — מחיר מקסימלי
  /setrooms 2-3     — טווח חדרים
  /setsize 50       — מינימום מ"ר
  /reset            — חזרה לברירת מחדל
"""

import json, os, re, time, threading, requests
from datetime import datetime

# ══════════════════════════════════════════════════════
#  הגדרות
# ══════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "")
SUPABASE_URL       = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY       = os.environ.get("SUPABASE_KEY", "")
ADMIN_USER_ID      = 336895483

DEFAULT_FILTERS = {
    "max_price": 5500,
    "min_rooms": 2.0,
    "max_rooms": 3.0,
    "min_size":  50,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# ══════════════════════════════════════════════════════
#  Supabase
# ══════════════════════════════════════════════════════

def sb_headers():
    return {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }

def sb_get(table: str, params: dict = None):
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={**sb_headers(), "Prefer": ""},
            params=params,
            timeout=10
        )
        return r.json() if r.ok else []
    except Exception as e:
        print(f"[{now_str()}] supabase get error: {e}")
        return []

def sb_upsert(table: str, data):
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={**sb_headers(), "Prefer": "resolution=merge-duplicates"},
            json=data,
            timeout=10
        )
    except Exception as e:
        print(f"[{now_str()}] supabase upsert error: {e}")

def sb_update(table: str, match: dict, data: dict):
    try:
        params = {k: f"eq.{v}" for k, v in match.items()}
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=sb_headers(),
            params=params,
            json=data,
            timeout=10
        )
    except Exception as e:
        print(f"[{now_str()}] supabase update error: {e}")

# ══════════════════════════════════════════════════════
#  ניהול פילטרים — Supabase
# ══════════════════════════════════════════════════════

def load_filters() -> dict:
    rows = sb_get("bot_filters")
    if not rows:
        return DEFAULT_FILTERS.copy()
    f = DEFAULT_FILTERS.copy()
    for row in rows:
        key, val = row.get("key"), row.get("value")
        if key in ("max_price", "min_size"):
            f[key] = int(val)
        elif key in ("min_rooms", "max_rooms"):
            f[key] = float(val)
    return f

def save_filters(filters: dict):
    rows = [{"key": k, "value": str(v)} for k, v in filters.items()]
    sb_upsert("bot_filters", rows)

def filters_summary(filters: dict) -> str:
    return (
        f"⚙️ <b>פילטרים נוכחיים:</b>\n\n"
        f"💰 מחיר מקסימלי: <b>{filters['max_price']:,} ₪</b>\n"
        f"🛏 חדרים: <b>{filters['min_rooms']:.1f}–{filters['max_rooms']:.1f}</b>\n"
        f"📐 שטח מינימלי: <b>{filters['min_size']} מ\"ר</b>"
    )

# ══════════════════════════════════════════════════════
#  ניהול דירות — Supabase
# ══════════════════════════════════════════════════════

def load_seen_ids() -> set:
    rows = sb_get("listings", {"select": "id"})
    return set(r["id"] for r in rows)

def save_listing(listing: dict):
    sb_upsert("listings", {
        "id":     listing["id"],
        "source": listing.get("source", ""),
        "city":   listing.get("city", "") or listing.get("label", "").split(",")[0],
        "street": listing.get("street", ""),
        "price":  listing.get("price", 0),
        "rooms":  str(listing.get("rooms", "")),
        "link":   listing.get("link", ""),
    })

# ══════════════════════════════════════════════════════
#  אזורי חיפוש
# ══════════════════════════════════════════════════════

_Y = "https://www.yad2.co.il/realestate/rent/center-and-sharon"
_K = "https://www.komo.co.il/code/nadlan/apartments-for-rent.asp"

YAD2_AREA_DEFS = [
    {"label": "נס ציונה",                  "params": "area=12&city=7200"},
    {"label": "באר יעקב",                  "params": "area=9&city=2530"},
    {"label": "נצר סירני",                 "params": "area=12&city=0435"},
    {"label": "אירוס",                     "params": "area=9&city=1336"},
    {"label": "בית חנן",                   "params": "area=9&city=0159"},
    {"label": "נטעים",                     "params": "area=9&city=0174"},
    {"label": "גן שורק",                   "params": "area=9&city=0311"},
    {"label": "עיינות",                    "params": "area=9&city=0156"},
    {"label": "יד רמבם",                   "params": "area=92&city=0064"},
    {"label": "כלניות, ראשון לציון",       "params": "area=9&city=8300&neighborhood=469"},
    {"label": "שיכוני המזרח, ראשון לציון", "params": "area=9&city=8300&neighborhood=283"},
    {"label": "מישור הנוף, ראשון לציון",   "params": "area=9&city=8300&neighborhood=303"},
    {"label": "הרקפות, ראשון לציון",       "params": "area=9&city=8300&neighborhood=991415"},
    {"label": "חצבים, ראשון לציון",        "params": "area=9&city=8300&neighborhood=991419"},
    {"label": "נרקיסים, ראשון לציון",      "params": "area=9&city=8300&neighborhood=991420"},
    {"label": "נוריות, ראשון לציון",       "params": "area=9&city=8300&neighborhood=991421"},
    {"label": "צמרות, ראשון לציון",        "params": "area=9&city=8300&neighborhood=299"},
    {"label": "נווה עמית, רחובות",         "params": "area=12&city=8400&neighborhood=1211"},
    {"label": "בית עובד",                  "params": "area=9&city=0202"},
]

KOMO_AREA_DEFS = [
    {"label": "נס ציונה",                  "city": "%D7%A0%D7%A1+%D7%A6%D7%99%D7%95%D7%A0%D7%94"},
    {"label": "באר יעקב",                  "city": "%D7%91%D7%90%D7%A8+%D7%99%D7%A2%D7%A7%D7%91"},
    {"label": "אירוס",                     "city": "%D7%90%D7%99%D7%A8%D7%95%D7%A1"},
    {"label": "בית חנן",                   "city": "%D7%91%D7%99%D7%AA+%D7%97%D7%A0%D7%9F"},
    {"label": "נטעים",                     "city": "%D7%A0%D7%98%D7%A2%D7%99%D7%9D"},
    {"label": "גן שורק",                   "city": "%D7%92%D7%9F+%D7%A9%D7%95%D7%A8%D7%A7"},
    {"label": "עיינות",                    "city": "%D7%A2%D7%99%D7%99%D7%A0%D7%95%D7%AA"},
    {"label": "יד רמבם",                   "city": "%D7%99%D7%93+%D7%A8%D7%9E%D7%91%26quot%3B%D7%9D"},
    {"label": "כלניות, ראשון לציון",       "city": "%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F", "hood": "neighborhoodNum=4648"},
    {"label": "שיכוני המזרח, ראשון לציון", "city": "%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F", "hood": "neighborhoodNum=524"},
    {"label": "מישור הנוף, ראשון לציון",   "city": "%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F", "hood": "neighborhoodNum=498"},
    {"label": "הרקפות, ראשון לציון",       "city": "%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F", "hood": "neighborhoodNum=4331"},
    {"label": "נרקיסים, ראשון לציון",      "city": "%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F", "hood": "neighborhoodNum=4555"},
    {"label": "נוריות, ראשון לציון",       "city": "%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F", "hood": "neighborhoodNum=5189"},
    {"label": "נווה עמית, רחובות",         "city": "%D7%A8%D7%97%D7%95%D7%91%D7%95%D7%AA",                          "hood": "neighborhoodNum=541"},
    {"label": "בית עובד",                  "city": "%D7%91%D7%99%D7%AA+%D7%A2%D7%95%D7%91%D7%93"},
]

def build_yad2_params(f: dict) -> str:
    return f"maxPrice={f['max_price']}&minRooms={f['min_rooms']}&maxRooms={f['max_rooms']}&minSquaremeter={f['min_size']}"

def build_komo_params(f: dict) -> str:
    return f"fromRooms={f['min_rooms']}&toRooms={f['max_rooms']}&toPrice={f['max_price']}"

def get_yad2_areas(f: dict) -> list:
    p = build_yad2_params(f)
    return [{"label": a["label"], "url": f"{_Y}?{p}&{a['params']}"} for a in YAD2_AREA_DEFS]

def get_komo_areas(f: dict) -> list:
    p = build_komo_params(f)
    areas = []
    for a in KOMO_AREA_DEFS:
        hood = f"&{a['hood']}" if a.get("hood") else ""
        areas.append({"label": a["label"], "url": f"{_K}?cityName={a['city']}{hood}&{p}"})
    return areas

# ══════════════════════════════════════════════════════
#  פונקציות עזר
# ══════════════════════════════════════════════════════

def now_str():
    return datetime.now().strftime("%H:%M:%S")

def is_time_to_check() -> bool:
    t = datetime.now()
    m = t.hour * 60 + t.minute
    if 5 * 60 + 30 <= m < 23 * 60 + 30:
        return t.minute % 15 == 0
    return (t.hour == 23 and t.minute == 30) or (t.hour == 5 and t.minute == 30)

def send_telegram(message: str, reply_markup=None):
    try:
        payload = {
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10
        ).raise_for_status()
    except Exception as e:
        print(f"[{now_str()}] Telegram error: {e}")

def answer_callback(callback_id: str, text: str = ""):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text},
            timeout=10
        )
    except Exception:
        pass

def fetch_html(url: str, homepage: str = None):
    try:
        session = requests.Session()
        if homepage:
            session.get(homepage, headers=HEADERS, timeout=15)
            time.sleep(1)
        resp = session.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            return resp.text
        print(f"[{now_str()}] HTTP {resp.status_code} — {url[:70]}")
        return None
    except Exception as e:
        print(f"[{now_str()}] fetch error: {e}")
        return None

def format_message(l: dict) -> str:
    floor_str = f"\n🏢 קומה: {l['floor']}" if l.get("floor") else ""
    hood_str  = f"\n🏘 שכונה: {l['hood']}"  if l.get("hood")  else ""
    price_str = f"{l['price']:,}" if l.get("price") else "לא צוין"
    size_str  = f"{l['size']} מ\"ר" if l.get("size") else "לא צוין"
    return (
        f"🏠 <b>[{l['source']}] {l['label']}</b>\n\n"
        f"📍 {l['city']} - {l['street']}{hood_str}{floor_str}\n"
        f"🛏 חדרים: {l['rooms']}\n"
        f"📐 שטח: {size_str}\n"
        f"💰 מחיר: {price_str} ₪\n"
        f"🔗 <a href=\"{l['link']}\">לצפייה במודעה</a>"
    )

# ══════════════════════════════════════════════════════
#  יד2 — סקרפר
# ══════════════════════════════════════════════════════

def parse_yad2(html: str, label: str) -> list:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not m:
        return []
    try:
        feed  = json.loads(m.group(1))["props"]["pageProps"]["feed"]
        items = feed.get("private", []) + feed.get("agency", []) + feed.get("platinum", [])
        out   = []
        for item in items:
            token = item.get("token", "")
            if not token:
                continue
            addr = item.get("address", {})
            det  = item.get("additionalDetails", {})
            out.append({
                "id":     f"yad2_{token}",
                "source": "יד2",
                "label":  label,
                "price":  item.get("price", 0),
                "rooms":  det.get("roomsCount", ""),
                "size":   det.get("squareMeter", ""),
                "city":   addr.get("city",         {}).get("text", ""),
                "street": (addr.get("street", {}).get("text", "") + " " +
                           str(addr.get("house", {}).get("number", ""))).strip(),
                "hood":   addr.get("neighborhood", {}).get("text", ""),
                "floor":  addr.get("house",        {}).get("floor", ""),
                "link":   f"https://www.yad2.co.il/item/{token}",
            })
        return out
    except Exception as e:
        print(f"[{now_str()}] yad2 parse error {label}: {e}")
        return []

def scrape_yad2(filters: dict) -> list:
    results = []
    for area in get_yad2_areas(filters):
        html = fetch_html(area["url"], homepage="https://www.yad2.co.il")
        if html:
            listings = parse_yad2(html, area["label"])
            print(f"[{now_str()}] יד2  | {len(listings):2d} — {area['label']}")
            results.extend(listings)
        time.sleep(2)
    return results

# ══════════════════════════════════════════════════════
#  קומו — סקרפר (תוקן)
# ══════════════════════════════════════════════════════

def parse_komo(html: str, label: str) -> list:
    listings = []
    seen_ids = set()
    for m in re.finditer(r'modaaNum=(\d+)', html):
        mid = m.group(1)
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        pos   = m.start()
        # tdPrice נמצא ~574 לפני, LinkModaaTitle ~342 לפני
        block = html[max(0, pos - 700):pos + 200]

        # מחיר — חפש class tdPrice ואז מספר לפני ₪
        price = 0
        price_m = re.search(r'tdPrice[^>]*>[\s]*([\d,]+)\s*[₪\u20aa]', block)
        if price_m:
            try:
                price = int(price_m.group(1).replace(",", ""))
            except ValueError:
                pass

        # כתובת — חפש class LinkModaaTitle ואז הטקסט
        street = ""
        street_m = re.search(r'LinkModaaTitle[^>]*>(.*?)</span>', block, re.DOTALL)
        if street_m:
            street = re.sub(r'<[^>]+>', '', street_m.group(1)).strip()

        # חדרים
        rooms_m = re.search(r'([\d.]+)\s*חדרים', block)
        rooms   = rooms_m.group(1) if rooms_m else ""

        # שטח
        size_m = re.search(r'\((\d+)\s*מ', block)
        size   = size_m.group(1) if size_m else ""

        # קומה
        floor_m = re.search(r'קומה[:\s]*(\d+)', block)
        floor   = floor_m.group(1) if floor_m else ""

        listings.append({
            "id":     f"komo_{mid}",
            "source": "קומו",
            "label":  label,
            "price":  price,
            "rooms":  rooms,
            "size":   size,
            "city":   label.split(",")[0],
            "street": street,
            "hood":   "",
            "floor":  floor,
            "link":   f"https://www.komo.co.il/code/nadlan/details/?modaaNum={mid}",
        })
    return listings

def scrape_komo(filters: dict) -> list:
    results = []
    for area in get_komo_areas(filters):
        html = fetch_html(area["url"])
        if html:
            listings = parse_komo(html, area["label"])
            print(f"[{now_str()}] קומו | {len(listings):2d} — {area['label']}")
            results.extend(listings)
        time.sleep(2)
    return results

SCRAPERS = [
    ("יד2",  scrape_yad2),
    ("קומו", scrape_komo),
]

# ══════════════════════════════════════════════════════
#  מסך /seen
# ══════════════════════════════════════════════════════

seen_state = {
    "sources":   set(),
    "cities":    set(),
    "rooms":     set(),
    "min_price": None,
    "max_price": None,
}

MIN_PRICE_OPTIONS = [0, 2000, 3000, 4000, 5000]
MAX_PRICE_OPTIONS = [4000, 5000, 5500, 6000, 7000, 8000]
ROOMS_OPTIONS     = ["1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5", "5"]

def get_seen_cities() -> list:
    rows = sb_get("listings", {"select": "city"})
    return sorted(set(r["city"] for r in rows if r.get("city")))

def tick(val, selected_set) -> str:
    return f"✅ {val}" if val in selected_set else str(val)

def tick_price(val, current) -> str:
    label = "ללא" if val == 0 else f"{val:,}"
    return f"✅ {label}" if val == current else label

def build_seen_keyboard() -> dict:
    s = seen_state
    cities = get_seen_cities()

    city_rows, row = [], []
    for city in cities:
        row.append({"text": tick(city, s["cities"]), "callback_data": f"seen_tog_city_{city}"})
        if len(row) == 2:
            city_rows.append(row)
            row = []
    if row:
        city_rows.append(row)

    rooms_rows, row = [], []
    for r in ROOMS_OPTIONS:
        row.append({"text": tick(r, s["rooms"]), "callback_data": f"seen_tog_rooms_{r}"})
        if len(row) == 3:
            rooms_rows.append(row)
            row = []
    if row:
        rooms_rows.append(row)

    keyboard = [
        [{"text": "── אתר ──", "callback_data": "seen_noop"}],
        [
            {"text": tick("יד2",  s["sources"]), "callback_data": "seen_tog_src_יד2"},
            {"text": tick("קומו", s["sources"]), "callback_data": "seen_tog_src_קומו"},
        ],
        [{"text": "── עיר ──", "callback_data": "seen_noop"}],
        *city_rows,
        [{"text": "── חדרים ──", "callback_data": "seen_noop"}],
        *rooms_rows,
        [{"text": "── מחיר מינימום ──", "callback_data": "seen_noop"}],
        [{"text": tick_price(p, s["min_price"]), "callback_data": f"seen_min_{p}"} for p in MIN_PRICE_OPTIONS[:3]],
        [{"text": tick_price(p, s["min_price"]), "callback_data": f"seen_min_{p}"} for p in MIN_PRICE_OPTIONS[3:]],
        [{"text": "── מחיר מקסימום ──", "callback_data": "seen_noop"}],
        [{"text": tick_price(p, s["max_price"]), "callback_data": f"seen_max_{p}"} for p in MAX_PRICE_OPTIONS[:3]],
        [{"text": tick_price(p, s["max_price"]), "callback_data": f"seen_max_{p}"} for p in MAX_PRICE_OPTIONS[3:]],
        [
            {"text": "🔍 חפש", "callback_data": "seen_search"},
            {"text": "🔄 נקה", "callback_data": "seen_clear"},
        ],
    ]
    return {"inline_keyboard": keyboard}

def reset_seen_state():
    seen_state["sources"]   = set()
    seen_state["cities"]    = set()
    seen_state["rooms"]     = set()
    seen_state["min_price"] = None
    seen_state["max_price"] = None

def send_seen_menu():
    reset_seen_state()
    total = len(sb_get("listings", {"select": "id"}))
    send_telegram(
        f"🔍 <b>חיפוש דירות שנסרקו</b> — {total} בסך הכל\n\nבחר מסננים ולחץ 🔍 חפש:",
        reply_markup=build_seen_keyboard()
    )

def run_seen_search():
    s = seen_state
    params = {"select": "source,city,street,price,rooms,link", "order": "seen_at.desc"}

    filters = []
    if s["sources"]:
        src_list = ",".join(s["sources"])
        params["source"] = f"in.({src_list})"
    if s["cities"]:
        city_list = ",".join(s["cities"])
        params["city"] = f"in.({city_list})"
    if s["min_price"] is not None and s["min_price"] > 0:
        filters.append(("price", "gte", s["min_price"]))
    if s["max_price"] is not None:
        filters.append(("price", "lte", s["max_price"]))

    # Supabase תומך בפרמטרים מרובים לאותו שדה דרך headers
    rows = sb_get("listings", params)

    # סינון price ו-rooms בצד הלקוח
    if s["min_price"] is not None and s["min_price"] > 0:
        rows = [r for r in rows if (r.get("price") or 0) >= s["min_price"]]
    if s["max_price"] is not None:
        rows = [r for r in rows if (r.get("price") or 0) <= s["max_price"]]
    if s["rooms"]:
        rows = [r for r in rows if str(r.get("rooms", "")) in s["rooms"]]

    if not rows:
        send_telegram("📭 לא נמצאו דירות לפי הסינון שנבחר.")
        return

    lines = [f"🏠 <b>תוצאות חיפוש ({len(rows)} דירות):</b>\n"]
    for r in rows:
        price = f"{r['price']:,}₪" if r.get("price") else "?"
        lines.append(
            f"• <b>{r.get('source','')}</b> | {r.get('city','')} {r.get('street','')} | "
            f"{r.get('rooms','')}חד׳ | {price} — <a href=\"{r.get('link','')}\">קישור</a>"
        )

    chunk, chunks = [], []
    for line in lines:
        chunk.append(line)
        if len("\n".join(chunk)) > 3800:
            chunks.append("\n".join(chunk[:-1]))
            chunk = [line]
    chunks.append("\n".join(chunk))
    for msg in chunks:
        if msg.strip():
            send_telegram(msg)
            time.sleep(0.3)

# ══════════════════════════════════════════════════════
#  תפריט /filters
# ══════════════════════════════════════════════════════

def send_filters_menu(filters: dict):
    keyboard = {
        "inline_keyboard": [
            [{"text": f"💰 מחיר: {filters['max_price']:,}₪",                              "callback_data": "menu_price"}],
            [{"text": f"🛏 חדרים: {filters['min_rooms']:.1f}–{filters['max_rooms']:.1f}", "callback_data": "menu_rooms"}],
            [{"text": f"📐 שטח מינ': {filters['min_size']} מ\"ר",                         "callback_data": "menu_size"}],
            [{"text": "🔄 איפוס לברירת מחדל",                                             "callback_data": "cmd_reset"}],
        ]
    }
    send_telegram(filters_summary(filters) + "\n\nלחץ על כפתור לשינוי:", reply_markup=keyboard)

# ══════════════════════════════════════════════════════
#  טיפול בפקודות טלגרם
# ══════════════════════════════════════════════════════

_last_update_id = 0

def handle_command(text: str, user_id: int):
    filters = load_filters()
    text    = text.strip()

    if text.startswith("/status"):
        return filters_summary(filters)

    if text.startswith("/seen"):
        send_seen_menu()
        return None

    if text.startswith("/filters"):
        send_filters_menu(filters)
        return None

    if user_id != ADMIN_USER_ID:
        return "⛔ רק המנהל יכול לשנות פילטרים."

    if text.startswith("/reset"):
        save_filters(DEFAULT_FILTERS.copy())
        return "✅ פילטרים אופסו לברירת מחדל!\n\n" + filters_summary(DEFAULT_FILTERS)

    m = re.match(r'/setprice\S*\s+(\d+)', text)
    if m:
        val = int(m.group(1))
        if val < 1000 or val > 20000:
            return "❌ מחיר חייב להיות בין 1,000 ל-20,000 ₪"
        filters["max_price"] = val
        save_filters(filters)
        return f"✅ מחיר מקסימלי עודכן ל-{val:,} ₪\n\n" + filters_summary(filters)

    m = re.match(r'/setrooms\S*\s+([\d.]+)-([\d.]+)', text)
    if m:
        mn, mx = float(m.group(1)), float(m.group(2))
        if mn < 1 or mx > 10 or mn > mx:
            return "❌ טווח חדרים לא תקין (לדוג׳: 2-3)"
        filters["min_rooms"] = mn
        filters["max_rooms"] = mx
        save_filters(filters)
        return f"✅ חדרים עודכנו ל-{mn:.1f}–{mx:.1f}\n\n" + filters_summary(filters)

    m = re.match(r'/setsize\S*\s+(\d+)', text)
    if m:
        val = int(m.group(1))
        if val < 10 or val > 300:
            return "❌ שטח חייב להיות בין 10 ל-300 מ\"ר"
        filters["min_size"] = val
        save_filters(filters)
        return f"✅ שטח מינימלי עודכן ל-{val} מ\"ר\n\n" + filters_summary(filters)

    if text.startswith("/"):
        return (
            "📋 <b>פקודות זמינות:</b>\n\n"
            "/status — פילטרים נוכחיים\n"
            "/filters — תפריט שינוי פילטרים\n"
            "/seen — חיפוש דירות שנסרקו\n"
            "/setprice 5500 — מחיר מקסימלי\n"
            "/setrooms 2-3 — טווח חדרים\n"
            "/setsize 50 — מינימום מ\"ר\n"
            "/reset — ברירת מחדל"
        )
    return None

def handle_callback(cb: dict):
    cid     = cb["id"]
    data    = cb.get("data", "")
    user_id = cb["from"]["id"]

    if data == "seen_noop":
        answer_callback(cid)
        return

    if data == "seen_clear":
        reset_seen_state()
        answer_callback(cid, "🔄 מסננים נוקו")
        send_telegram("🔍 מסננים נוקו — בחר מחדש:", reply_markup=build_seen_keyboard())
        return

    if data == "seen_search":
        answer_callback(cid, "🔍 מחפש...")
        run_seen_search()
        return

    if data.startswith("seen_tog_src_"):
        src = data[len("seen_tog_src_"):]
        seen_state["sources"].discard(src) if src in seen_state["sources"] else seen_state["sources"].add(src)
        answer_callback(cid)
        send_telegram("🔍 עדכן מסננים:", reply_markup=build_seen_keyboard())
        return

    if data.startswith("seen_tog_city_"):
        city = data[len("seen_tog_city_"):]
        seen_state["cities"].discard(city) if city in seen_state["cities"] else seen_state["cities"].add(city)
        answer_callback(cid)
        send_telegram("🔍 עדכן מסננים:", reply_markup=build_seen_keyboard())
        return

    if data.startswith("seen_tog_rooms_"):
        r = data[len("seen_tog_rooms_"):]
        seen_state["rooms"].discard(r) if r in seen_state["rooms"] else seen_state["rooms"].add(r)
        answer_callback(cid)
        send_telegram("🔍 עדכן מסננים:", reply_markup=build_seen_keyboard())
        return

    if data.startswith("seen_min_"):
        val = int(data.split("_")[-1])
        seen_state["min_price"] = None if seen_state["min_price"] == val else val
        answer_callback(cid)
        send_telegram("🔍 עדכן מסננים:", reply_markup=build_seen_keyboard())
        return

    if data.startswith("seen_max_"):
        val = int(data.split("_")[-1])
        seen_state["max_price"] = None if seen_state["max_price"] == val else val
        answer_callback(cid)
        send_telegram("🔍 עדכן מסננים:", reply_markup=build_seen_keyboard())
        return

    if user_id != ADMIN_USER_ID:
        answer_callback(cid, "⛔ רק המנהל יכול לשנות פילטרים.")
        return

    filters = load_filters()
    price_options = [3000, 3500, 4000, 4500, 5000, 5500, 6000, 7000]
    rooms_options = [("1–2", 1.0, 2.0), ("2–3", 2.0, 3.0), ("2–3.5", 2.0, 3.5),
                     ("2.5–4", 2.5, 4.0), ("3–4", 3.0, 4.0), ("3–5", 3.0, 5.0)]
    size_options  = [30, 40, 50, 60, 70, 80]

    if data == "menu_price":
        keyboard = {"inline_keyboard": [
            [{"text": f"{'✅ ' if filters['max_price']==p else ''}{p:,}₪", "callback_data": f"set_price_{p}"} for p in price_options[:4]],
            [{"text": f"{'✅ ' if filters['max_price']==p else ''}{p:,}₪", "callback_data": f"set_price_{p}"} for p in price_options[4:]],
            [{"text": "« חזרה", "callback_data": "menu_back"}],
        ]}
        answer_callback(cid)
        send_telegram("💰 בחר מחיר מקסימלי:", reply_markup=keyboard)
        return

    if data == "menu_rooms":
        keyboard = {"inline_keyboard": [
            [{"text": f"{'✅ ' if filters['min_rooms']==mn and filters['max_rooms']==mx else ''}{lbl}",
              "callback_data": f"set_rooms_{mn}_{mx}"} for lbl, mn, mx in rooms_options],
            [{"text": "« חזרה", "callback_data": "menu_back"}],
        ]}
        answer_callback(cid)
        send_telegram("🛏 בחר טווח חדרים:", reply_markup=keyboard)
        return

    if data == "menu_size":
        keyboard = {"inline_keyboard": [
            [{"text": f"{'✅ ' if filters['min_size']==s else ''}{s} מ\"ר", "callback_data": f"set_size_{s}"} for s in size_options[:3]],
            [{"text": f"{'✅ ' if filters['min_size']==s else ''}{s} מ\"ר", "callback_data": f"set_size_{s}"} for s in size_options[3:]],
            [{"text": "« חזרה", "callback_data": "menu_back"}],
        ]}
        answer_callback(cid)
        send_telegram("📐 בחר שטח מינימלי:", reply_markup=keyboard)
        return

    if data == "menu_back":
        answer_callback(cid)
        send_filters_menu(load_filters())
        return

    if data == "cmd_reset":
        save_filters(DEFAULT_FILTERS.copy())
        answer_callback(cid, "✅ אופס!")
        send_telegram("✅ פילטרים אופסו!\n\n" + filters_summary(DEFAULT_FILTERS))
        return

    if data.startswith("set_price_"):
        val = int(data.split("_")[-1])
        filters["max_price"] = val
        save_filters(filters)
        answer_callback(cid, f"✅ {val:,} ₪")
        send_telegram(f"✅ מחיר עודכן ל-{val:,} ₪\n\n" + filters_summary(filters))
        return

    if data.startswith("set_rooms_"):
        parts = data.split("_")
        mn, mx = float(parts[2]), float(parts[3])
        filters["min_rooms"] = mn
        filters["max_rooms"] = mx
        save_filters(filters)
        answer_callback(cid, "✅ חדרים עודכנו")
        send_telegram(f"✅ חדרים עודכנו ל-{mn:.1f}–{mx:.1f}\n\n" + filters_summary(filters))
        return

    if data.startswith("set_size_"):
        val = int(data.split("_")[-1])
        filters["min_size"] = val
        save_filters(filters)
        answer_callback(cid, f"✅ {val} מ\"ר")
        send_telegram(f"✅ שטח עודכן ל-{val} מ\"ר\n\n" + filters_summary(filters))
        return

    answer_callback(cid)

def poll_telegram():
    global _last_update_id
    print(f"[{now_str()}] 📡 מאזין לפקודות טלגרם...")
    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                params={"offset": _last_update_id + 1, "timeout": 30},
                timeout=40
            )
            for update in resp.json().get("result", []):
                _last_update_id = update["update_id"]
                msg = update.get("message") or update.get("edited_message")
                if msg and msg.get("text") and msg["text"].startswith("/"):
                    reply = handle_command(msg["text"], msg["from"]["id"])
                    if reply:
                        send_telegram(reply)
                cb = update.get("callback_query")
                if cb:
                    handle_callback(cb)
        except Exception as e:
            print(f"[{now_str()}] polling error: {e}")
            time.sleep(5)

# ══════════════════════════════════════════════════════
#  ריצה ראשית
# ══════════════════════════════════════════════════════

def check_all():
    filters  = load_filters()
    seen_ids = load_seen_ids()
    print(f"\n[{now_str()}] 🔍 בודק | מחיר≤{filters['max_price']} | {filters['min_rooms']:.1f}-{filters['max_rooms']:.1f}חד' | {filters['min_size']}מ\"ר+")
    total_new = 0
    for name, scraper in SCRAPERS:
        print(f"[{now_str()}] ── {name} ──")
        try:
            listings = scraper(filters)
        except Exception as e:
            print(f"[{now_str()}] error {name}: {e}")
            continue
        new_count = 0
        for l in listings:
            if l["id"] and l["id"] not in seen_ids:
                send_telegram(format_message(l))
                save_listing(l)
                seen_ids.add(l["id"])
                print(f"[{now_str()}] 🆕 [{name}] {l['label']} | {l['rooms']}חד' | {l['price']}₪")
                new_count += 1
                total_new += 1
                time.sleep(1)
        print(f"[{now_str()}] {name}: {len(listings)} נבדקו, {new_count} חדשות")
    print(f"[{now_str()}] סיום. {'🎉 ' + str(total_new) + ' חדשות!' if total_new else 'אין חדש.'}")

def scan_silent():
    filters  = load_filters()
    seen_ids = load_seen_ids()
    count    = 0
    for name, scraper in SCRAPERS:
        print(f"[{now_str()}] סורק {name} בשקט...")
        try:
            for l in scraper(filters):
                if l["id"] and l["id"] not in seen_ids:
                    save_listing(l)
                    seen_ids.add(l["id"])
                    count += 1
        except Exception as e:
            print(f"[{now_str()}] error {name}: {e}")
    return count

if __name__ == "__main__":
    filters = load_filters()
    n = len(YAD2_AREA_DEFS) + len(KOMO_AREA_DEFS)
    print("╔══════════════════════════════════════════════════╗")
    print("║       מוניטור דירות — יד2 + קומו — פועל!       ║")
    print("║  05:30–23:30  →  כל 15 דקות                    ║")
    print("║  23:30–05:30  →  רק ב-23:30 ושוב ב-05:30       ║")
    print(f"║  {filters['min_rooms']:.1f}-{filters['max_rooms']:.1f} חדרים | {filters['min_size']}+ מ\u05f4ר | עד {filters['max_price']:,}\u20aa         \u2551")
    print(f"║  {n} אזורים על פני {len(SCRAPERS)} אתרים                        ║")
    print("╚══════════════════════════════════════════════════╝\n")

    threading.Thread(target=poll_telegram, daemon=True).start()

    existing = load_seen_ids()
    if not existing:
        print(f"[{now_str()}] 🚀 הפעלה ראשונה — סורק הכל בשקט (ללא התראות)...")
        count = scan_silent()
        print(f"[{now_str()}] ✅ נשמרו {count} מודעות ב-DB. מעכשיו — רק חדשות!\n")
    else:
        check_all()

    while True:
        time.sleep(60 - datetime.now().second)
        if is_time_to_check():
            check_all()
