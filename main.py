#!/usr/bin/env python3
"""
מוניטור דירות — יד2 + קומו (+ הומלס בקרוב)
בוט טלגרם אחד שבודק את כל האתרים.

לוח זמנים:
  05:30–23:30  → בדיקה כל 15 דקות
  23:30–05:30  → בדיקה ב-23:30 ושוב ב-05:30
"""

import json, os, re, time, requests
from datetime import datetime

# ══════════════════════════════════════════════════════
#  הגדרות
# ══════════════════════════════════════════════════════

SEEN_IDS_FILE      = "seen_listings.json"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "")

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
#  יד2 — אזורי חיפוש
# ══════════════════════════════════════════════════════

_Y  = "https://www.yad2.co.il/realestate/rent/center-and-sharon"
_YP = "maxPrice=5500&minRooms=2&maxRooms=3&minSquaremeter=50"

YAD2_AREAS = [
    {"label": "נס ציונה",                  "url": f"{_Y}?{_YP}&area=12&city=7200"},
    {"label": "באר יעקב",                  "url": f"{_Y}?{_YP}&area=9&city=2530"},
    {"label": "נצר סירני",                 "url": f"{_Y}?{_YP}&area=12&city=0435"},
    {"label": "אירוס",                     "url": f"{_Y}?{_YP}&area=9&city=1336"},
    {"label": "בית חנן",                   "url": f"{_Y}?{_YP}&area=9&city=0159"},
    {"label": "נטעים",                     "url": f"{_Y}?{_YP}&area=9&city=0174"},
    {"label": "גן שורק",                   "url": f"{_Y}?{_YP}&area=9&city=0311"},
    {"label": "עיינות",                    "url": f"{_Y}?{_YP}&area=9&city=0156"},
    {"label": "יד רמב\"ם",                 "url": f"{_Y}?{_YP}&area=92&city=0064"},
    {"label": "כלניות, ראשון לציון",       "url": f"{_Y}?{_YP}&area=9&city=8300&neighborhood=469"},
    {"label": "שיכוני המזרח, ראשון לציון", "url": f"{_Y}?{_YP}&area=9&city=8300&neighborhood=283"},
    {"label": "מישור הנוף, ראשון לציון",   "url": f"{_Y}?{_YP}&area=9&city=8300&neighborhood=303"},
    {"label": "הרקפות, ראשון לציון",       "url": f"{_Y}?{_YP}&area=9&city=8300&neighborhood=991415"},
    {"label": "חצבים, ראשון לציון",        "url": f"{_Y}?{_YP}&area=9&city=8300&neighborhood=991419"},
    {"label": "נרקיסים, ראשון לציון",      "url": f"{_Y}?{_YP}&area=9&city=8300&neighborhood=991420"},
    {"label": "נוריות, ראשון לציון",       "url": f"{_Y}?{_YP}&area=9&city=8300&neighborhood=991421"},
    {"label": "צמרות, ראשון לציון",        "url": f"{_Y}?{_YP}&area=9&city=8300&neighborhood=299"},
    {"label": "נווה עמית, רחובות",         "url": f"{_Y}?{_YP}&area=12&city=8400&neighborhood=1211"},
]

# ══════════════════════════════════════════════════════
#  קומו — אזורי חיפוש
# ══════════════════════════════════════════════════════

_K  = "https://www.komo.co.il/code/nadlan/apartments-for-rent.asp"
_KP = "fromRooms=2&toRooms=3&toPrice=5500"

KOMO_AREAS = [
    {"label": "נס ציונה",                  "url": f"{_K}?cityName=%D7%A0%D7%A1+%D7%A6%D7%99%D7%95%D7%A0%D7%94&{_KP}"},
    {"label": "באר יעקב",                  "url": f"{_K}?cityName=%D7%91%D7%90%D7%A8+%D7%99%D7%A2%D7%A7%D7%91&{_KP}"},
    {"label": "אירוס",                     "url": f"{_K}?cityName=%D7%90%D7%99%D7%A8%D7%95%D7%A1&{_KP}"},
    {"label": "בית חנן",                   "url": f"{_K}?cityName=%D7%91%D7%99%D7%AA+%D7%97%D7%A0%D7%9F&{_KP}"},
    {"label": "נטעים",                     "url": f"{_K}?cityName=%D7%A0%D7%98%D7%A2%D7%99%D7%9D&{_KP}"},
    {"label": "גן שורק",                   "url": f"{_K}?cityName=%D7%92%D7%9F+%D7%A9%D7%95%D7%A8%D7%A7&{_KP}"},
    {"label": "עיינות",                    "url": f"{_K}?cityName=%D7%A2%D7%99%D7%99%D7%A0%D7%95%D7%AA&{_KP}"},
    {"label": "יד רמב\"ם",                 "url": f"{_K}?cityName=%D7%99%D7%93+%D7%A8%D7%9E%D7%91%26quot%3B%D7%9D&{_KP}"},
    {"label": "כלניות, ראשון לציון",       "url": f"{_K}?cityName=%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F&neighborhoodNum=4648&{_KP}"},
    {"label": "שיכוני המזרח, ראשון לציון", "url": f"{_K}?cityName=%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F&neighborhoodNum=524&{_KP}"},
    {"label": "מישור הנוף, ראשון לציון",   "url": f"{_K}?cityName=%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F&neighborhoodNum=498&{_KP}"},
    {"label": "הרקפות, ראשון לציון",       "url": f"{_K}?cityName=%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F&neighborhoodNum=4331&{_KP}"},
    {"label": "נרקיסים, ראשון לציון",      "url": f"{_K}?cityName=%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F&neighborhoodNum=4555&{_KP}"},
    {"label": "נוריות, ראשון לציון",       "url": f"{_K}?cityName=%D7%A8%D7%90%D7%A9%D7%95%D7%9F+%D7%9C%D7%A6%D7%99%D7%95%D7%9F&neighborhoodNum=5189&{_KP}"},
    {"label": "נווה עמית, רחובות",         "url": f"{_K}?cityName=%D7%A8%D7%97%D7%95%D7%91%D7%95%D7%AA&neighborhoodNum=541&{_KP}"},
]

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

def send_telegram(message: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10
        ).raise_for_status()
    except Exception as e:
        print(f"[{now_str()}] Telegram error: {e}")

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

def scrape_yad2() -> list:
    results = []
    for area in YAD2_AREAS:
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

def scrape_komo() -> list:
    results = []
    for area in KOMO_AREAS:
        html = fetch_html(area["url"])
        if html:
            listings = parse_komo(html, area["label"])
            print(f"[{now_str()}] קומו | {len(listings):2d} — {area['label']}")
            results.extend(listings)
        time.sleep(2)
    return results

# ══════════════════════════════════════════════════════
#  הומלס — סקרפר
# ══════════════════════════════════════════════════════

HOMELESS_AREAS = [
    {"label": "נס ציונה",  "url": "https://www.homeless.co.il/rent/city=%d7%a0%d7%a1%20%d7%a6%d7%99%d7%95%d7%a0%d7%94$$inumber4=3$$inumber4_1=5$$flong3_1=5500"},
    {"label": "באר יעקב", "url": "https://www.homeless.co.il/rent/city=%d7%91%d7%90%d7%a8%20%d7%99%d7%a2%d7%a7%d7%91$$inumber4=3$$inumber4_1=5$$flong3_1=5500"},
    {"label": "נצר סירני", "url": "https://www.homeless.co.il/rent/city=%d7%a0%d7%a6%d7%a8%20%d7%a1%d7%99%d7%a8%d7%a0%d7%99$$inumber4=3$$inumber4_1=5$$flong3_1=5500"},
    {"label": "בית חנן",   "url": "https://www.homeless.co.il/rent/city=%d7%91%d7%99%d7%aa%20%d7%97%d7%a0%d7%9f$$inumber4=3$$inumber4_1=5$$flong3_1=5500"},
    {"label": "נטעים",     "url": "https://www.homeless.co.il/rent/city=%d7%a0%d7%98%d7%a2%d7%99%d7%9d$$inumber4=3$$inumber4_1=5$$flong3_1=5500"},
    {"label": "גן שורק",   "url": "https://www.homeless.co.il/rent/city=%d7%92%d7%9f%20%d7%a9%d7%95%d7%a8%d7%a7$$inumber4=3$$inumber4_1=5$$flong3_1=5500"},
    {"label": "עיינות",    "url": "https://www.homeless.co.il/rent/city=%d7%a2%d7%99%d7%99%d7%a0%d7%95%d7%aa$$inumber4=3$$inumber4_1=5$$flong3_1=5500"},
    {"label": "יד רמב\"ם", "url": "https://www.homeless.co.il/rent/city=%d7%99%d7%93%20%d7%a8%d7%9e%d7%91quot%d7%9d$$inumber4=3$$inumber4_1=5$$flong3_1=5500"},
]

def parse_homeless(html: str, label: str) -> list:
    """
    הומלס — HTML ישן עם טבלת mainresults.
    כל שורה: id="ad_713282"
    עמודות: [סוג, עיר, שכונה, רחוב, חדרים, קומה, מחיר, כניסה, תאריך]
    לינק: /rent/viewad,713282.aspx
    """
    from html.parser import HTMLParser

    class HomelessParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_table   = False
            self.in_row     = False
            self.current_id = None
            self.current_tds = []
            self.current_td_text = []
            self.in_td      = 0
            self.current_link = ""
            self.results    = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "table" and attrs.get("id") == "mainresults":
                self.in_table = True
            if not self.in_table:
                return
            if tag == "tr":
                row_id = attrs.get("id", "")
                if row_id.startswith("ad_"):
                    self.in_row     = True
                    self.current_id = row_id[3:]  # הסר "ad_"
                    self.current_tds = []
                    self.current_link = ""
            if self.in_row:
                if tag == "td":
                    self.in_td += 1
                    self.current_td_text = []
                if tag == "a" and "href" in attrs:
                    href = attrs["href"]
                    if "viewad" in href:
                        self.current_link = href if href.startswith("http") else f"https://www.homeless.co.il{href}"

        def handle_endtag(self, tag):
            if not self.in_table:
                return
            if tag == "td" and self.in_row and self.in_td > 0:
                self.current_tds.append(" ".join(self.current_td_text).strip())
                self.in_td -= 1
            if tag == "tr" and self.in_row:
                self.in_row = False
                tds = self.current_tds
                # עמודות: 0=ריק, 1=ריק, 2=סוג, 3=עיר, 4=שכונה, 5=רחוב, 6=חדרים, 7=קומה, 8=מחיר
                if len(tds) >= 9 and self.current_id:
                    price_raw = tds[8].replace("₪", "").replace(",", "").strip()
                    try:
                        price = int(price_raw)
                    except ValueError:
                        price = 0
                    self.results.append({
                        "id":     f"homeless_{self.current_id}",
                        "source": "הומלס",
                        "label":  label,
                        "price":  price,
                        "rooms":  tds[6],
                        "size":   "",
                        "city":   tds[3],
                        "street": tds[5],
                        "hood":   tds[4],
                        "floor":  tds[7],
                        "link":   self.current_link,
                    })
                self.current_id = None

        def handle_data(self, data):
            if self.in_row and self.in_td > 0:
                text = data.strip()
                if text:
                    self.current_td_text.append(text)

    parser = HomelessParser()
    try:
        parser.feed(html)
    except Exception as e:
        print(f"[{now_str()}] homeless parse error {label}: {e}")
    return parser.results

def scrape_homeless() -> list:
    results = []
    for area in HOMELESS_AREAS:
        html = fetch_html(area["url"])
        if html:
            listings = parse_homeless(html, area["label"])
            print(f"[{now_str()}] הומלס| {len(listings):2d} — {area['label']}")
            results.extend(listings)
        time.sleep(2)
    return results

# ══════════════════════════════════════════════════════
#  ריצה ראשית
# ══════════════════════════════════════════════════════

SCRAPERS = [
    ("יד2",   scrape_yad2),
    ("קומו",  scrape_komo),
    ("הומלס", scrape_homeless),
]

def check_all():
    print(f"\n[{now_str()}] 🔍 בודק {len(SCRAPERS)} אתרים...")
    seen_ids  = load_seen_ids()
    total_new = 0

    for name, scraper in SCRAPERS:
        print(f"[{now_str()}] ── {name} ──")
        try:
            listings = scraper()
        except Exception as e:
            print(f"[{now_str()}] error {name}: {e}")
            continue
        new_count = 0
        for l in listings:
            if l["id"] and l["id"] not in seen_ids:
                send_telegram(format_message(l))
                print(f"[{now_str()}] 🆕 [{name}] {l['label']} | {l['rooms']} חד׳ | {l['price']}₪")
                seen_ids.add(l["id"])
                new_count += 1
                total_new += 1
                time.sleep(1)
        print(f"[{now_str()}] {name}: {len(listings)} נבדקו, {new_count} חדשות")

    save_seen_ids(seen_ids)
    print(f"[{now_str()}] סיום. {'🎉 ' + str(total_new) + ' חדשות!' if total_new else 'אין חדש.'}")

def scan_silent() -> set:
    all_ids = set()
    for name, scraper in SCRAPERS:
        print(f"[{now_str()}] סורק {name} בשקט...")
        try:
            for l in scraper():
                if l["id"]:
                    all_ids.add(l["id"])
        except Exception as e:
            print(f"[{now_str()}] error {name}: {e}")
    return all_ids

if __name__ == "__main__":
    n = len(YAD2_AREAS) + len(KOMO_AREAS)
    print("╔══════════════════════════════════════════════════╗")
    print("║   מוניטור דירות — יד2 + קומו + הומלס — פועל!  ║")
    print("║  05:30–23:30  →  כל 15 דקות                    ║")
    print("║  23:30–05:30  →  רק ב-23:30 ושוב ב-05:30       ║")
    print(f"║  2-3 חדרים | 50+ מ״ר | עד 5500₪               ║")
    print(f"║  {n} אזורים על פני {len(SCRAPERS)} אתרים                      ║")
    print("╚══════════════════════════════════════════════════╝\n")

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
