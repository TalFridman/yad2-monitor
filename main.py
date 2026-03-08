#!/usr/bin/env python3
"""
יד2 מוניטור דירות — גרסה סופית

איך הסקריפט יודע מה "חדש":
  כל מודעה מקבלת token ייחודי מיד2 (למשל "t7u4pkiu").
  בהפעלה הראשונה: הסקריפט סורק את כל הדירות הקיימות,
  שומר את כל ה-tokens בקובץ seen_listings.json, ולא שולח כלום.
  מהבדיקה השנייה: רק tokens שלא היו בקובץ = דירה חדשה → התראה.

לוח זמנים:
  05:30 - 23:30  →  בדיקה כל 15 דקות
  23:30 - 05:30  →  בדיקה ב-23:30 ושוב ב-05:30
"""

import json
import os
import re
import time
import requests
from datetime import datetime

SEEN_IDS_FILE = "seen_listings.json"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "")

BASE_PARAMS = "maxPrice=5500&minRooms=2&maxRooms=3&minSquaremeter=50"
BASE = "https://www.yad2.co.il/realestate/rent/center-and-sharon"

SEARCH_AREAS = [
    {"label": "נס ציונה",                    "url": f"{BASE}?{BASE_PARAMS}&area=12&city=7200"},
    {"label": "באר יעקב",                    "url": f"{BASE}?{BASE_PARAMS}&area=9&city=2530"},
    {"label": "נצר סירני",                   "url": f"{BASE}?{BASE_PARAMS}&area=12&city=0435"},
    {"label": "אירוס",                       "url": f"{BASE}?{BASE_PARAMS}&area=9&city=1336"},
    {"label": "בית חנן",                     "url": f"{BASE}?{BASE_PARAMS}&area=9&city=0159"},
    {"label": "נטעים",                       "url": f"{BASE}?{BASE_PARAMS}&area=9&city=0174"},
    {"label": "גן שורק",                     "url": f"{BASE}?{BASE_PARAMS}&area=9&city=0311"},
    {"label": "עיינות",                      "url": f"{BASE}?{BASE_PARAMS}&area=9&city=0156"},
    {"label": "יד רמב\"ם",                   "url": f"{BASE}?{BASE_PARAMS}&area=92&city=0064"},
    {"label": "כלניות, ראשון לציון",         "url": f"{BASE}?{BASE_PARAMS}&area=9&city=8300&neighborhood=469"},
    {"label": "שיכוני המזרח, ראשון לציון",   "url": f"{BASE}?{BASE_PARAMS}&area=9&city=8300&neighborhood=283"},
    {"label": "מישור הנוף, ראשון לציון",     "url": f"{BASE}?{BASE_PARAMS}&area=9&city=8300&neighborhood=303"},
    {"label": "הרקפות, ראשון לציון",         "url": f"{BASE}?{BASE_PARAMS}&area=9&city=8300&neighborhood=991415"},
    {"label": "חצבים, ראשון לציון",          "url": f"{BASE}?{BASE_PARAMS}&area=9&city=8300&neighborhood=991419"},
    {"label": "נרקיסים, ראשון לציון",        "url": f"{BASE}?{BASE_PARAMS}&area=9&city=8300&neighborhood=991420"},
    {"label": "נוריות, ראשון לציון",         "url": f"{BASE}?{BASE_PARAMS}&area=9&city=8300&neighborhood=991421"},
    {"label": "צמרות, ראשון לציון",          "url": f"{BASE}?{BASE_PARAMS}&area=9&city=8300&neighborhood=299"},
    {"label": "נווה עמית, רחובות",           "url": f"{BASE}?{BASE_PARAMS}&area=12&city=8400&neighborhood=1211"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


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


def parse_listings(html: str, area_label: str) -> list:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.DOTALL
    )
    if not match:
        return []
    try:
        data  = json.loads(match.group(1))
        feed  = data["props"]["pageProps"]["feed"]
        items = feed.get("private", []) + feed.get("agency", []) + feed.get("platinum", [])
        listings = []
        for item in items:
            token   = item.get("token", "")
            price   = item.get("price", 0)
            details = item.get("additionalDetails", {})
            rooms   = details.get("roomsCount", "")
            size    = details.get("squareMeter", "")
            address = item.get("address", {})
            city    = address.get("city",         {}).get("text", "")
            street  = address.get("street",       {}).get("text", "")
            house   = address.get("house",        {}).get("number", "")
            hood    = address.get("neighborhood", {}).get("text", "")
            floor   = address.get("house",        {}).get("floor", "")
            if token:
                listings.append({
                    "id": token, "area_label": area_label,
                    "price": price, "rooms": rooms, "size": size,
                    "city": city, "street": f"{street} {house}".strip(),
                    "hood": hood, "floor": floor,
                    "link": f"https://www.yad2.co.il/item/{token}",
                })
        return listings
    except Exception as e:
        print(f"[{now_str()}] שגיאת parse ב-{area_label}: {e}")
        return []


def fetch_listings(area: dict) -> list:
    try:
        session = requests.Session()
        session.get("https://www.yad2.co.il", headers=HEADERS, timeout=15)
        time.sleep(1)
        resp = session.get(area["url"], headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            return parse_listings(resp.text, area["label"])
        print(f"[{now_str()}] HTTP {resp.status_code} ב-{area['label']}")
        return []
    except Exception as e:
        print(f"[{now_str()}] שגיאה ב-{area['label']}: {e}")
        return []


def send_telegram(message: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10
        ).raise_for_status()
    except Exception as e:
        print(f"[{now_str()}] שגיאת Telegram: {e}")


def scan_all_areas(silent: bool = False) -> set:
    """סורק את כל האזורים ומחזיר set של כל ה-IDs שנמצאו."""
    all_ids = set()
    for area in SEARCH_AREAS:
        listings = fetch_listings(area)
        for listing in listings:
            if listing["id"]:
                all_ids.add(listing["id"])
                if not silent:
                    # שלח התראה
                    floor_str = f"\n🏢 קומה: {listing['floor']}" if listing['floor'] != "" else ""
                    hood_str  = f"\n🏘 שכונה: {listing['hood']}" if listing['hood'] else ""
                    send_telegram(
                        f"🏠 <b>דירה חדשה! {listing['area_label']}</b>\n\n"
                        f"📍 {listing['city']} - {listing['street']}{hood_str}{floor_str}\n"
                        f"🛏 חדרים: {listing['rooms']}\n"
                        f"📐 שטח: {listing['size']} מ\"ר\n"
                        f"💰 מחיר: {listing['price']:,} ₪\n"
                        f"🔗 <a href=\"{listing['link']}\">לצפייה במודעה</a>"
                    )
                    print(f"[{now_str()}] 🆕 {listing['area_label']} | {listing['street']} | {listing['rooms']} חד׳ | {listing['price']}₪")
                    time.sleep(1)
        status = f"{len(listings)} נבדקו" if listings else "0"
        print(f"[{now_str()}] ✓  {status} — {area['label']}")
        time.sleep(2)
    return all_ids


def check_all_areas():
    print(f"\n[{now_str()}] 🔍 בודק {len(SEARCH_AREAS)} אזורים...")
    seen_ids  = load_seen_ids()
    total_new = 0

    for area in SEARCH_AREAS:
        listings    = fetch_listings(area)
        new_in_area = 0
        for listing in listings:
            if listing["id"] and listing["id"] not in seen_ids:
                floor_str = f"\n🏢 קומה: {listing['floor']}" if listing['floor'] != "" else ""
                hood_str  = f"\n🏘 שכונה: {listing['hood']}" if listing['hood'] else ""
                send_telegram(
                    f"🏠 <b>דירה חדשה! {listing['area_label']}</b>\n\n"
                    f"📍 {listing['city']} - {listing['street']}{hood_str}{floor_str}\n"
                    f"🛏 חדרים: {listing['rooms']}\n"
                    f"📐 שטח: {listing['size']} מ\"ר\n"
                    f"💰 מחיר: {listing['price']:,} ₪\n"
                    f"🔗 <a href=\"{listing['link']}\">לצפייה במודעה</a>"
                )
                print(f"[{now_str()}] 🆕 {area['label']} | {listing['street']} | {listing['rooms']} חד׳ | {listing['price']}₪")
                seen_ids.add(listing["id"])
                new_in_area += 1
                total_new   += 1
                time.sleep(1)
        status = f"{len(listings)} נבדקו" if listings else "0"
        print(f"[{now_str()}] {'🆕 ' + str(new_in_area) if new_in_area else '✓  ' + status} — {area['label']}")
        time.sleep(2)

    save_seen_ids(seen_ids)
    print(f"[{now_str()}] סיום. {'🎉 ' + str(total_new) + ' חדשות!' if total_new else 'אין חדש.'}")


if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════╗")
    print("║       יד2 מוניטור דירות — פועל!                ║")
    print("║  05:30–23:30  →  כל 15 דקות                    ║")
    print("║  23:30–05:30  →  רק ב-23:30 ושוב ב-05:30       ║")
    print(f"║  2-3 חדרים | 50+ מ״ר | עד 5500₪               ║")
    print(f"║  {len(SEARCH_AREAS)} אזורים                                   ║")
    print("╚══════════════════════════════════════════════════╝\n")

    if not os.path.exists(SEEN_IDS_FILE):
        # הפעלה ראשונה — סרוק הכל בשקט, שמור IDs, אל תשלח כלום
        print(f"[{now_str()}] 🚀 הפעלה ראשונה — סורק דירות קיימות (לא ישלח התראות)...")
        existing_ids = scan_all_areas(silent=True)
        save_seen_ids(existing_ids)
        print(f"[{now_str()}] ✅ נשמרו {len(existing_ids)} דירות קיימות. מעכשיו — רק דירות חדשות יישלחו!\n")
    else:
        # הפעלות הבאות — בדיקה רגילה
        check_all_areas()

    while True:
        seconds_to_next_minute = 60 - datetime.now().second
        time.sleep(seconds_to_next_minute)
        if is_time_to_check():
            check_all_areas()
