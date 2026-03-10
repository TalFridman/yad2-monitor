#!/usr/bin/env python3
"""
script חד-פעמי — מעדכן מחיר וכתובת לכל דירות קומו שכבר ב-DB.
הרץ פעם אחת אחרי deploy, אל תמחק.
"""

import os, re, time, requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
}

_K = "https://www.komo.co.il/code/nadlan/apartments-for-rent.asp"

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

def sb_headers():
    return {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
    }

def sb_update(mid: str, price: int, street: str):
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/listings",
        headers=sb_headers(),
        params={"id": f"eq.komo_{mid}"},
        json={"price": price, "street": street},
        timeout=10
    )

def fetch_html(url: str):
    try:
        resp = requests.get(url, headers=HEADERS_HTTP, timeout=20)
        return resp.text if resp.status_code == 200 else None
    except Exception as e:
        print(f"fetch error: {e}")
        return None

def parse_and_update(html: str, label: str) -> int:
    updated = 0
    seen_ids = set()
    for m in re.finditer(r'modaaNum=(\d+)', html):
        mid = m.group(1)
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        pos   = m.start()
        block = html[max(0, pos - 700):pos + 200]

        price = 0
        price_m = re.search(r'tdPrice[^>]*>[\s]*([\d,]+)\s*[₪\u20aa]', block)
        if price_m:
            try:
                price = int(price_m.group(1).replace(",", ""))
            except ValueError:
                pass

        street = ""
        street_m = re.search(r'LinkModaaTitle[^>]*>(.*?)</span>', block, re.DOTALL)
        if street_m:
            street = re.sub(r'<[^>]+>', '', street_m.group(1)).strip()

        if price > 0 or street:
            sb_update(mid, price, street)
            updated += 1
            print(f"  עודכן komo_{mid} | {street} | {price:,}₪")

    return updated

if __name__ == "__main__":
    print("🔧 מתחיל עדכון דירות קומו ב-DB...\n")
    total = 0
    for area in KOMO_AREA_DEFS:
        hood = f"&{area['hood']}" if area.get("hood") else ""
        url  = f"{_K}?cityName={area['city']}{hood}&fromRooms=1&toRooms=10&toPrice=99999"
        print(f"סורק {area['label']}...")
        html = fetch_html(url)
        if html:
            n = parse_and_update(html, area["label"])
            print(f"  {area['label']}: {n} עודכנו")
            total += n
        time.sleep(2)

    print(f"\n✅ סיום! {total} דירות קומו עודכנו ב-DB.")
