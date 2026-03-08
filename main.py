#!/usr/bin/env python3
"""
יד2 מוניטור דירות — גרסה סופית
לוח זמנים:
  05:30 - 23:30  →  בדיקה כל 15 דקות
  23:30 - 05:30  →  בדיקה ב-23:30 בלבד, ואז שוב ב-05:30
"""

import json
import os
import time
import requests
from datetime import datetime, time as dtime

# ══════════════════════════════════════════════════════
#  ✏️  הגדרות — ערוך רק כאן
# ══════════════════════════════════════════════════════

MIN_PRICE = 0
MAX_PRICE = 5500
MIN_ROOMS = 2
MAX_ROOMS = 3

SEEN_IDS_FILE = "seen_listings.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "YOUR_CHAT_ID_HERE")

# ══════════════════════════════════════════════════════
#  🗺️  אזורי חיפוש — קודים מאומתים מ-API של יד2
# ══════════════════════════════════════════════════════

SEARCH_AREAS = [
    {"label": "נס ציונה",  "city": "7200", "area": "12", "topArea": "41"},
    {"label": "באר יעקב",  "city": "2530", "area": "9",  "topArea": "2"},
    {"label": "נטעים",     "city": "0174", "area": "9",  "topArea": "2"},
    {"label": "בית חנן",   "city": "0159", "area": "9",  "topArea": "2"},
    {"label": "אירוס",     "city": "1336", "area": "9",  "topArea": "2"},
    {"label": "בית דגן",   "city": "0466", "area": "9",  "topArea": "2"},
    {"label": "גן שורק",   "city": "0311", "area": "9",  "topArea": "2"},
    {"label": "שיכוני המזרח, ראשון לציון", "city": "8300", "hood": "283",    "area": "9", "topArea": "2"},
    {"label": "נרקיסים, ראשון לציון",       "city": "8300", "hood": "991420", "area": "9", "topArea": "2"},
    {"label": "צמרות, ראשון לציון",          "city": "8300", "hood": "299",    "area": "9", "topArea": "2"},
    {"label": "נוריות, ראשון לציון",         "city": "8300", "hood": "991421", "area": "9", "topArea": "2"},
    {"label": "מישור הנוף, ראשון לציון",    "city": "8300", "hood": "303",    "area": "9", "topArea": "2"},
    {"label": "הרקפות, ראשון לציון",         "city": "8300", "hood": "991415", "area": "9", "topArea": "2"},
    {"label": "חצבים, ראשון לציון",          "city": "8300", "hood": "991419", "area": "9", "topArea": "2"},
    {"label": "נווה עמית, רחובות",           "city": "8400", "hood": "1211",   "area": "12", "topArea": "41"},
]

# ══════════════════════════════════════════════════════
#  לוגיקה פנימית
# ══════════════════════════════════════════════════════

# Session עם headers שמחקים דפדפן ישראלי אמיתי
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://www.yad2.co.il",
    "Referer": "https://www.yad2.co.il/realestate/rent",
    "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
})


def now_str():
    return datetime.now().strftime("%H:%M:%S")


def is_time_to_check() -> bool:
    """מחזיר True אם הגיע הזמן לבדוק לפי לוח הזמנים"""
    t = datetime.now()
    minute_of_day = t.hour * 60 + t.minute
    MORNING = 5 * 60 + 30   # 05:30
    NIGHT   = 23 * 60 + 30  # 23:30

    if MORNING <= minute_of_day < NIGHT:
        # שעות פעילות — כל 15 דקות בדיוק
        return t.minute % 15 == 0
    else:
        # לילה — רק ב-23:30 או ב-05:30
        return (t.hour == 23 and t.minute == 30) or (t.hour == 5 and t.minute == 30)


def load_seen_ids():
    if os.path.exists(SEEN_IDS_FILE):
        with open(SEEN_IDS_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(ids: set):
    with open(SEEN_IDS_FILE, "w") as f:
        json.dump(list(ids), f)


def fetch_listings_for_area(area: dict) -> list:
    params = {
        "rooms":       f"{MIN_ROOMS}-{MAX_ROOMS}",
        "price":       f"{MIN_PRICE}-{MAX_PRICE}",
        "forceLdLoad": "true",
        "city":        area["city"],
    }
    if area.get("hood"):    params["neighborhood"] = area["hood"]
    if area.get("area"):    params["area"]         = area["area"]
    if area.get("topArea"): params["topArea"]      = area["topArea"]

    try:
        # קודם נבקר בדף הבית כדי לקבל cookies
        resp = session.get(
            "https://gw.yad2.co.il/feed-search-legacy/realestate/rent",
            params=params,
            timeout=20
        )
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("feed", {}).get("feed_items", [])
        return [
            {
                "id":         str(i.get("id", "")),
                "area_label": area["label"],
                "rooms":      i.get("RoomsTxt", ""),
                "price":      i.get("price", ""),
                "city":       i.get("city", ""),
                "street":     i.get("street", ""),
                "size":       i.get("squaremeter", ""),
                "link":       f"https://www.yad2.co.il/item/{i.get('id', '')}",
            }
            for i in items if i.get("type") == "ad"
        ]
    except requests.exceptions.HTTPError as e:
        print(f"[{now_str()}] HTTP {e.response.status_code} ב-{area['label']}")
        return []
    except Exception as e:
        print(f"[{now_str()}] שגיאה ב-{area['label']}: {e}")
        return []


def send_telegram(message: str):
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
        resp.raise_for_status()
        print(f"[{now_str()}] ✓ Telegram נשלח")
    except Exception as e:
        print(f"[{now_str()}] שגיאת Telegram: {e}")


def check_all_areas():
    print(f"\n[{now_str()}] 🔍 בודק {len(SEARCH_AREAS)} אזורים...")

    # אתחול session עם ביקור בדף הראשי (לקבלת cookies)
    try:
        session.get("https://www.yad2.co.il/realestate/rent", timeout=15)
    except Exception:
        pass

    seen_ids  = load_seen_ids()
    total_new = 0

    for area in SEARCH_AREAS:
        listings    = fetch_listings_for_area(area)
        new_in_area = 0
        for listing in listings:
            if listing["id"] and listing["id"] not in seen_ids:
                print(f"[{now_str()}] 🆕 {area['label']} | {listing['street']} | {listing['rooms']} חד׳ | {listing['price']}₪")
                send_telegram(
                    f"🏠 <b>דירה חדשה! {listing['area_label']}</b>\n\n"
                    f"📍 {listing['city']} - {listing['street']}\n"
                    f"🛏 חדרים: {listing['rooms']}\n"
                    f"💰 מחיר: {listing['price']} ₪\n"
                    f"📐 שטח: {listing['size']} מ\"ר\n"
                    f"🔗 <a href=\"{listing['link']}\">לצפייה במודעה</a>"
                )
                seen_ids.add(listing["id"])
                new_in_area += 1
                total_new   += 1
                time.sleep(1)

        status = f"{len(listings)} נבדקו" if listings else "0 תוצאות"
        print(f"[{now_str()}] {'🆕 ' + str(new_in_area) + ' חדש' if new_in_area else '✓  ' + status} — {area['label']}")
        time.sleep(2)

    save_seen_ids(seen_ids)
    print(f"[{now_str()}] סיום. {'🎉 ' + str(total_new) + ' מודעות חדשות!' if total_new else 'אין חדש.'}")


# ══════════════════════════════════════════════════════
#  הפעלה
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════╗")
    print("║       יד2 מוניטור דירות — פועל!                ║")
    print("║  05:30–23:30  →  כל 15 דקות                    ║")
    print("║  23:30–05:30  →  רק ב-23:30 ושוב ב-05:30       ║")
    print(f"║  {MIN_ROOMS}-{MAX_ROOMS} חדרים | עד {MAX_PRICE}₪ | {len(SEARCH_AREAS)} אזורים              ║")
    print("╚══════════════════════════════════════════════════╝\n")

    # בדיקה ראשונה מיד
    check_all_areas()

    # לולאה ראשית — מחכה עד תחילת הדקה הבאה ובודקת
    while True:
        seconds_to_next_minute = 60 - datetime.now().second
        time.sleep(seconds_to_next_minute)
        if is_time_to_check():
            check_all_areas()
