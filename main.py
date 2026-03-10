#!/usr/bin/env python3
"""
מוניטור דירות — יד2 + קומו
בוט טלגרם עם פילטרים דינמיים.

לוח זמנים:
  05:30–23:30  → בדיקה כל 15 דקות
  23:30–05:30  → בדיקה ב-23:30 ושוב ב-05:30

פקודות בוט:
  /status           — פילטרים נוכחיים
  /filters          — תפריט שינוי פילטרים
  /seen             — הצג דירות שנצפו
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

SEEN_IDS_FILE      = "seen_listings.json"
SEEN_DETAILS_FILE  = "seen_details.json"
FILTERS_FILE       = "filters.json"
MAX_SEEN_DETAILS   = 300  # מקסימום דירות שנשמרות בפירוט
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "")
ADMIN_USER_ID      = 336895483  # רק המשתמש הזה יכול לשנות פילטרים

DEFAULT_FILTERS = {
    "max_price":  5500,
    "min_rooms":  2.0,
    "max_rooms":  3.0,
    "min_size":   50,
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
#  ניהול פילטרים
# ══════════════════════════════════════════════════════

def load_filters() -> dict:
    if os.path.exists(FILTERS_FILE):
        try:
            with open(FILTERS_FILE, "r") as f:
                return {**DEFAULT_FILTERS, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_FILTERS.copy()

def save_filters(filters: dict):
    with open(FILTERS_FILE, "w") as f:
        json.dump(filters, f, ensure_ascii=False, indent=2)

def filters_summary(filters: dict) -> str:
    return (
        f"⚙️ <b>פילטרים נוכחיים:</b>\n\n"
        f"💰 מחיר מקסימלי: <b>{filters['max_price']:,} ₪</b>\n"
        f"🛏 חדרים: <b>{filters['min_rooms']:.0f}–{filters['max_rooms']:.0f}</b>\n"
        f'📐 שטח מינימלי: <b>{filters["min_size"]} מ"ר</b>'
    )

def build_yad2_params(f: dict) -> str:
    return f"maxPrice={f['max_price']}&minRooms={f['min_rooms']}&maxRooms={f['max_rooms']}&minSquaremeter={f['min_size']}"

def build_komo_params(f: dict) -> str:
    return f"fromRooms={f['min_rooms']}&toRooms={f['max_rooms']}&toPrice={f['max_price']}"

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

def load_seen_ids() -> set:
    if os.path.exists(SEEN_IDS_FILE):
        with open(SEEN_IDS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen_ids(ids: set):
    with open(SEEN_IDS_FILE, "w") as f:
        json.dump(list(ids), f)

def load_seen_details() -> list:
    if os.path.exists(SEEN_DETAILS_FILE):
        try:
            with open(SEEN_DETAILS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_seen_details(details: list):
    # שמור רק את ה-MAX_SEEN_DETAILS האחרונות
    with open(SEEN_DETAILS_FILE, "w", encoding="utf-8") as f:
        json.dump(details[-MAX_SEEN_DETAILS:], f, ensure_ascii=False, indent=2)

def add_seen_detail(listing: dict):
    details = load_seen_details()
    # הוסף רק אם לא קיים כבר
    if not any(d["id"] == listing["id"] for d in details):
        details.append({
            "id":     listing["id"],
            "source": listing.get("source", ""),
            "city":   listing.get("city", "") or listing.get("label", "").split(",")[0],
            "street": listing.get("street", ""),
            "price":  listing.get("price", 0),
            "rooms":  listing.get("rooms", ""),
            "link":   listing.get("link", ""),
        })
        save_seen_details(details)

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

def fetch_html(url: str, homepage: str = None, encoding: str = None):
    try:
        session = requests.Session()
        if homepage:
            session.get(homepage, headers=HEADERS, timeout=15)
            time.sleep(1)
        resp = session.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            if encoding:
                resp.encoding = encoding
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
    size_str  = f'{l["size"]} מ"ר' if l.get("size") else "לא צוין"
    return (
        f"🏠 <b>[{l['source']}] {l['label']}</b>\n\n"
        f"📍 {l['city']} - {l['street']}{hood_str}{floor_str}\n"
        f"🛏 חדרים: {l['rooms']}\n"
        f"📐 שטח: {size_str}\n"
        f"💰 מחיר: {price_str} ₪\n"
        f'🔗 <a href="{l["link"]}">לצפייה במודעה</a>'
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
#  קומו — סקרפר
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
        block = html[max(0, pos - 600):pos + 200]
        price_m = re.search(r'([\d,]+)\s*&#8362;|([0-9,]+)\s*₪', block)
        price   = 0
        if price_m:
            raw = (price_m.group(1) or price_m.group(2) or "0").replace(",", "")
            try:
                price = int(raw)
            except ValueError:
                pass
        rooms_m = re.search(r'([\d.]+)\s*חדרים', block)
        rooms   = rooms_m.group(1) if rooms_m else ""
        size_m  = re.search(r'\((\d+)\s*מ', block)
        size    = size_m.group(1) if size_m else ""
        floor_m = re.search(r'קומה[:\s]*(\d+)', block)
        floor   = floor_m.group(1) if floor_m else ""
        title_m = re.search(r'(?:title|alt)="([^"]{5,80})"', block)
        addr    = title_m.group(1) if title_m else ""
        listings.append({
            "id":     f"komo_{mid}",
            "source": "קומו",
            "label":  label,
            "price":  price,
            "rooms":  rooms,
            "size":   size,
            "city":   label.split(",")[0],
            "street": addr,
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

# ══════════════════════════════════════════════════════
#  טיפול בפקודות טלגרם
# ══════════════════════════════════════════════════════

_last_update_id = 0

# ── דירות שנצפו ──────────────────────────────────────

def send_seen_menu():
    details = load_seen_details()
    count   = len(details)
    sources = sorted(set(d["source"] for d in details))
    source_btns = [{"text": f"📋 {s}", "callback_data": f"seen_source_{s}"} for s in sources]
    keyboard = {"inline_keyboard": [
        [{"text": f"🏠 הצג הכל ({count} דירות)", "callback_data": "seen_all"}],
        source_btns if source_btns else [],
        [{"text": "« סגור", "callback_data": "seen_close"}],
    ]}
    send_telegram(f"🔍 <b>דירות שנצפו</b> — {count} בסך הכל\n\nבחר תצוגה:", reply_markup=keyboard)

def send_seen_all():
    details = load_seen_details()
    if not details:
        send_telegram("📭 אין דירות שנצפו עדיין.")
        return
    lines = [f"🏠 <b>כל הדירות שנצפו ({len(details)}):</b>\n"]
    for d in reversed(details):
        price = f"{d['price']:,}₪" if d.get("price") else "?"
        lines.append(
            f"• <b>{d['source']}</b> | {d.get('city','')} {d.get('street','')} | "
            f"{d.get('rooms','')}חד׳ | {price} — <a href=\"{d['link']}\">קישור</a>"
        )
    chunk, chunks = [], []
    for line in lines:
        chunk.append(line)
        if len("\n".join(chunk)) > 3500:
            chunks.append("\n".join(chunk[:-1]))
            chunk = [line]
    chunks.append("\n".join(chunk))
    for msg in chunks:
        send_telegram(msg)
        time.sleep(0.5)

def send_seen_by_source(source: str):
    details = [d for d in load_seen_details() if d["source"] == source]
    if not details:
        send_telegram(f"📭 אין דירות שנצפו מ-{source}.")
        return
    cities = sorted(set(d.get("city", "") for d in details if d.get("city")))
    city_btns, row = [], []
    for city in cities:
        cnt = sum(1 for d in details if d.get("city") == city)
        row.append({"text": f"{city} ({cnt})", "callback_data": f"seen_city_{source}|||{city}"})
        if len(row) == 2:
            city_btns.append(row)
            row = []
    if row:
        city_btns.append(row)
    city_btns.append([{"text": f"🏠 הכל מ-{source} ({len(details)})", "callback_data": f"seen_srcall_{source}"}])
    city_btns.append([{"text": "« חזרה", "callback_data": "seen_back"}])
    send_telegram(f"📋 <b>{source}</b> — {len(details)} דירות\n\nבחר עיר:", reply_markup={"inline_keyboard": city_btns})

def send_seen_by_city(source: str, city: str):
    details = [d for d in load_seen_details() if d["source"] == source and d.get("city") == city]
    if not details:
        send_telegram(f"📭 אין דירות מ-{source} ב{city}.")
        return
    lines = [f"📍 <b>{source} | {city} ({len(details)}):</b>\n"]
    for d in reversed(details):
        price = f"{d['price']:,}₪" if d.get("price") else "?"
        lines.append(f"• {d.get('street','')} | {d.get('rooms','')}חד׳ | {price} — <a href=\"{d['link']}\">קישור</a>")
    send_telegram("\n".join(lines))

def send_seen_srcall(source: str):
    details = [d for d in load_seen_details() if d["source"] == source]
    if not details:
        send_telegram(f"📭 אין דירות מ-{source}.")
        return
    lines = [f"📋 <b>{source} — {len(details)} דירות:</b>\n"]
    for d in reversed(details):
        price = f"{d['price']:,}₪" if d.get("price") else "?"
        lines.append(
            f"• {d.get('city','')} {d.get('street','')} | {d.get('rooms','')}חד׳ | {price} — <a href=\"{d['link']}\">קישור</a>"
        )
    chunk, chunks = [], []
    for line in lines:
        chunk.append(line)
        if len("\n".join(chunk)) > 3500:
            chunks.append("\n".join(chunk[:-1]))
            chunk = [line]
    chunks.append("\n".join(chunk))
    for msg in chunks:
        send_telegram(msg)
        time.sleep(0.5)

def send_filters_menu(filters: dict):
    keyboard = {
        "inline_keyboard": [
            [{"text": f"💰 מחיר: {filters['max_price']:,}₪",                    "callback_data": "menu_price"}],
            [{"text": f"🛏 חדרים: {filters['min_rooms']:.0f}–{filters['max_rooms']:.0f}", "callback_data": "menu_rooms"}],
            [{"text": f"📐 שטח מינ': {filters['min_size']} מ\"ר",               "callback_data": "menu_size"}],
            [{"text": "🔄 איפוס לברירת מחדל",                                   "callback_data": "cmd_reset"}],
        ]
    }
    send_telegram(filters_summary(filters) + "\n\nלחץ על כפתור לשינוי:", reply_markup=keyboard)

def handle_command(text: str, user_id: int):
    filters = load_filters()
    text = text.strip()

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
        return f"✅ חדרים עודכנו ל-{mn:.0f}–{mx:.0f}\n\n" + filters_summary(filters)

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
            "/seen — דירות שנצפו\n"
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

    if user_id != ADMIN_USER_ID:
        answer_callback(cid, "⛔ רק המנהל יכול לשנות פילטרים.")
        return

    filters = load_filters()

    price_options = [3000, 3500, 4000, 4500, 5000, 5500, 6000, 7000]
    rooms_options = [("1–2", 1.0, 2.0), ("2–3", 2.0, 3.0), ("2.5–4", 2.5, 4.0), ("3–4", 3.0, 4.0), ("3–5", 3.0, 5.0)]
    size_options  = [30, 40, 50, 60, 70, 80]

    if data == "seen_all":
        answer_callback(cid)
        send_seen_all()
        return

    if data == "seen_back":
        answer_callback(cid)
        send_seen_menu()
        return

    if data == "seen_close":
        answer_callback(cid, "סגור ✓")
        return

    if data.startswith("seen_source_"):
        source = data[len("seen_source_"):]
        answer_callback(cid)
        send_seen_by_source(source)
        return

    if data.startswith("seen_city_"):
        parts = data[len("seen_city_"):].split("|||", 1)
        if len(parts) == 2:
            answer_callback(cid)
            send_seen_by_city(parts[0], parts[1])
        return

    if data.startswith("seen_srcall_"):
        source = data[len("seen_srcall_"):]
        answer_callback(cid)
        send_seen_srcall(source)
        return

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
        send_filters_menu(filters)
        return

    if data == "cmd_reset":
        save_filters(DEFAULT_FILTERS.copy())
        answer_callback(cid, "✅ אופס!")
        send_telegram("✅ פילטרים אופסו לברירת מחדל!\n\n" + filters_summary(DEFAULT_FILTERS))
        return

    if data.startswith("set_price_"):
        val = int(data.split("_")[-1])
        filters["max_price"] = val
        save_filters(filters)
        answer_callback(cid, f"✅ מחיר עודכן ל-{val:,} ₪")
        send_telegram(f"✅ מחיר מקסימלי עודכן ל-{val:,} ₪\n\n" + filters_summary(filters))
        return

    if data.startswith("set_rooms_"):
        parts = data.split("_")
        mn, mx = float(parts[2]), float(parts[3])
        filters["min_rooms"] = mn
        filters["max_rooms"] = mx
        save_filters(filters)
        answer_callback(cid, f"✅ חדרים עודכנו")
        send_telegram(f"✅ חדרים עודכנו ל-{mn:.0f}–{mx:.0f}\n\n" + filters_summary(filters))
        return

    if data.startswith("set_size_"):
        val = int(data.split("_")[-1])
        filters["min_size"] = val
        save_filters(filters)
        answer_callback(cid, f"✅ שטח עודכן ל-{val} מ\"ר")
        send_telegram(f"✅ שטח מינימלי עודכן ל-{val} מ\"ר\n\n" + filters_summary(filters))
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

SCRAPERS = [
    ("יד2",  scrape_yad2),
    ("קומו", scrape_komo),
]

def check_all():
    filters = load_filters()
    print(f"\n[{now_str()}] 🔍 בודק | מחיר≤{filters['max_price']} | {filters['min_rooms']:.0f}-{filters['max_rooms']:.0f}חד' | {filters['min_size']}מ\"ר+")
    seen_ids  = load_seen_ids()
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
                add_seen_detail(l)
                print(f"[{now_str()}] 🆕 [{name}] {l['label']} | {l['rooms']}חד' | {l['price']}₪")
                seen_ids.add(l["id"])
                new_count += 1
                total_new += 1
                time.sleep(1)
        print(f"[{now_str()}] {name}: {len(listings)} נבדקו, {new_count} חדשות")
    save_seen_ids(seen_ids)
    print(f"[{now_str()}] סיום. {'🎉 ' + str(total_new) + ' חדשות!' if total_new else 'אין חדש.'}")

def scan_silent() -> set:
    filters = load_filters()
    all_ids = set()
    for name, scraper in SCRAPERS:
        print(f"[{now_str()}] סורק {name} בשקט...")
        try:
            for l in scraper(filters):
                if l["id"]:
                    all_ids.add(l["id"])
        except Exception as e:
            print(f"[{now_str()}] error {name}: {e}")
    return all_ids

if __name__ == "__main__":
    filters = load_filters()
    n = len(YAD2_AREA_DEFS) + len(KOMO_AREA_DEFS)
    print("╔══════════════════════════════════════════════════╗")
    print("║       מוניטור דירות — יד2 + קומו — פועל!       ║")
    print("║  05:30–23:30  →  כל 15 דקות                    ║")
    print("║  23:30–05:30  →  רק ב-23:30 ושוב ב-05:30       ║")
    print(f"║  {filters['min_rooms']:.0f}-{filters['max_rooms']:.0f} חדרים | {filters['min_size']}+ מ\u05f4ר | עד {filters['max_price']:,}\u20aa          \u2551")
    print(f"║  {n} אזורים על פני {len(SCRAPERS)} אתרים                        ║")
    print("╚══════════════════════════════════════════════════╝\n")

    threading.Thread(target=poll_telegram, daemon=True).start()

    if not os.path.exists(SEEN_IDS_FILE):
        print(f"[{now_str()}] 🚀 הפעלה ראשונה — סורק הכל בשקט (ללא התראות)...")
        existing = scan_silent()
        save_seen_ids(existing)
        print(f"[{now_str()}] ✅ נשמרו {len(existing)} מודעות. מעכשיו — רק חדשות!\n")
    else:
        check_all()

    while True:
        time.sleep(60 - datetime.now().second)
        if is_time_to_check():
            check_all()
