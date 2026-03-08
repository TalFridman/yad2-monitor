#!/usr/bin/env python3
"""
יד2 מוניטור דירות — גרסה סופית
לוח זמנים:
  05:30 - 23:30  →  בדיקה כל 15 דקות
  23:30 - 05:30  →  בדיקה ב-23:30 בלבד, ואז שוב ב-05:30

התקנה:
    pip install requests schedule
"""

import json
import os
import time
import schedule
import smtplib
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ══════════════════════════════════════════════════════
#  ✏️  הגדרות — ערוך רק כאן
# ══════════════════════════════════════════════════════

MIN_PRICE = 0
MAX_PRICE = 5500
MIN_ROOMS = 2
MAX_ROOMS = 3

SEEN_IDS_FILE = "seen_listings.json"

# Telegram: שלח הודעה ל-@BotFather ← /newbot ← קבל TOKEN
# אחר כך: https://api.telegram.org/bot<TOKEN>/getUpdates  ← קבל chat_id
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID   = "YOUR_CHAT_ID_HERE"

# ══════════════════════════════════════════════════════
#  🗺️  אזורי חיפוש — קודים מאומתים מ-API של יד2
# ══════════════════════════════════════════════════════

SEARCH_AREAS = [
    # ── ערים מלאות ──────────────────────────────────
    {"label": "נס ציונה",  "city": "7200", "area": "12", "topArea": "41"},
    {"label": "באר יעקב",  "city": "2530", "area": "9",  "topArea": "2"},
    {"label": "נטעים",     "city": "0174", "area": "9",  "topArea": "2"},
    {"label": "בית חנן",   "city": "0159", "area": "9",  "topArea": "2"},
    {"label": "אירוס",     "city": "1336", "area": "9",  "topArea": "2"},
    {"label": "גן שורק",   "city": "0311", "area": "9",  "topArea": "2"},

    # ── שכונות ראשון לציון ───────────────────────────
    {"label": "שיכוני המזרח, ראשון לציון", "city": "8300", "hood": "283",    "area": "9", "topArea": "2"},
    {"label": "נרקיסים, ראשון לציון",       "city": "8300", "hood": "991420", "area": "9", "topArea": "2"},
    {"label": "צמרות, ראשון לציון",          "city": "8300", "hood": "299",    "area": "9", "topArea": "2"},
    {"label": "נוריות, ראשון לציון",         "city": "8300", "hood": "991421", "area": "9", "topArea": "2"},
    {"label": "מישור הנוף, ראשון לציון",    "city": "8300", "hood": "303",    "area": "9", "topArea": "2"},
    {"label": "הרקפות, ראשון לציון",         "city": "8300", "hood": "991415", "area": "9", "topArea": "2"},
    {"label": "חצבים, ראשון לציון",          "city": "8300", "hood": "991419", "area": "9", "topArea": "2"},

    # ── שכונה ברחובות ────────────────────────────────
    {"label": "נווה עמית, רחובות", "city": "8400", "hood": "1211", "area": "12", "topArea": "41"},
]

# ══════════════════════════════════════════════════════
#  לוגיקה — אין צורך לערוך מכאן
# ══════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Referer": "https://www.yad2.co.il/",
}


def now_str():
    return datetime.now().strftime("%H:%M:%S")


def is_active_hours() -> bool:
    """מחזיר True בין 05:30 ל-23:30"""
    t = datetime.now().time()
    from datetime import time as dtime
    return dtime(5, 30) <= t < dtime(23, 30)


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
    if area.get("hood"):
        params["neighborhood"] = area["hood"]
    if area.get("area"):
        params["area"] = area["area"]
    if area.get("topArea"):
        params["topArea"] = area["topArea"]

    try:
        resp = requests.get(
            "https://gw.yad2.co.il/feed-search-legacy/realestate/rent",
            params=params, headers=HEADERS, timeout=15
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
    except Exception as e:
        print(f"[{now_str()}] שגיאת Telegram: {e}")


def notify(listing: dict):
    send_telegram(
        f"🏠 <b>דירה חדשה! {listing['area_label']}</b>\n\n"
        f"📍 {listing['city']} - {listing['street']}\n"
        f"🛏 חדרים: {listing['rooms']}\n"
        f"💰 מחיר: {listing['price']} ₪\n"
        f"📐 שטח: {listing['size']} מ\"ר\n"
        f"🔗 <a href=\"{listing['link']}\">לצפייה במודעה</a>"
    )


def check_all_areas():
    print(f"\n[{now_str()}] 🔍 בודק {len(SEARCH_AREAS)} אזורים...")
    seen_ids  = load_seen_ids()
    total_new = 0

    for area in SEARCH_AREAS:
        listings    = fetch_listings_for_area(area)
        new_in_area = 0
        for listing in listings:
            if listing["id"] and listing["id"] not in seen_ids:
                print(f"[{now_str()}] 🆕 {area['label']} | {listing['street']} | {listing['rooms']} חד׳ | {listing['price']}₪")
                notify(listing)
                seen_ids.add(listing["id"])
                new_in_area += 1
                total_new   += 1
                time.sleep(1)
        if listings and new_in_area == 0:
            print(f"[{now_str()}] ✓  {area['label']}: {len(listings)} נבדקו")
        time.sleep(2)

    save_seen_ids(seen_ids)
    print(f"[{now_str()}] {'🎉 ' + str(total_new) + ' מודעות חדשות!' if total_new else 'אין חדש.'}")


def smart_check():
    """
    מופעל כל דקה על ידי הלולאה הראשית.
    מחליט האם לבצע בדיקה עכשיו לפי לוח הזמנים:
      05:30 - 23:30  → כל 15 דקות
      23:30          → בדיקה אחת, ואז שוב ב-05:30
    """
    t = datetime.now()
    minute = t.hour * 60 + t.minute   # דקה מתחילת היום

    MORNING  = 5  * 60 + 30   # 05:30 = 330
    NIGHT    = 23 * 60 + 30   # 23:30 = 1410

    if MORNING <= minute < NIGHT:
        # שעות פעילות — בדוק כל 15 דקות בדיוק
        if t.minute % 15 == 0:
            check_all_areas()
    else:
        # שעות לילה — רק ב-23:30 או ב-05:30
        if (t.hour == 23 and t.minute == 30) or (t.hour == 5 and t.minute == 30):
            check_all_areas()


# ══════════════════════════════════════════════════════
#  הפעלה
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════╗")
    print("║       יד2 מוניטור דירות — פועל!                ║")
    print("║  05:30–23:30  →  בדיקה כל 15 דקות              ║")
    print("║  23:30–05:30  →  בדיקה ב-23:30 ושוב ב-05:30    ║")
    print(f"║  {MIN_ROOMS}-{MAX_ROOMS} חדרים | עד {MAX_PRICE}₪ | {len(SEARCH_AREAS)} אזורים           ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    # בדיקה ראשונה מיד בהפעלה
    check_all_areas()

    # לולאה ראשית — בודקת כל דקה אם הגיע הזמן
    while True:
        smart_check()
        # ממתין עד תחילת הדקה הבאה
        seconds_to_next_minute = 60 - datetime.now().second
        time.sleep(seconds_to_next_minute)
