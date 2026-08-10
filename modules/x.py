import os
import re
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

# ตารางแปลงชื่อเดือนภาษาไทยเป็นตัวเลข (1-12)
THAI_MONTH_TO_INT = {
    "ม.ค.": 1, "ม.ค": 1,
    "ก.พ.": 2, "ก.พ": 2,
    "มี.ค.": 3, "มี.ค": 3,
    "เม.ย.": 4, "เม.ย": 4,
    "พ.ค.": 5, "พ.ค": 5,
    "มิ.ย.": 6, "มิ.ย": 6,
    "ก.ค.": 7, "ก.ค": 7,
    "ส.ค.": 8, "ส.ค": 8,
    "ก.ย.": 9, "ก.ย": 9,
    "ต.ค.": 10, "ต.ค": 10,
    "พ.ย.": 11, "พ.ย": 11,
    "ธ.ค.": 12, "ธ.ค": 12,
}

COMMON_STOPWORDS = {"ไทยพีบีเอส", "thaipbs", "live", "สด", "น", "recap", "hd", "ถ่ายทอดสด"}


def create_driver(headless: bool = True) -> webdriver.Chrome:
    """
    สร้างและตั้งค่า Selenium Chrome WebDriver พร้อม Stealth Arguments (สำหรับ X / Twitter)
    """
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")

    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=th-TH,th")
    chrome_options.add_argument("--mute-audio")

    # ป้องกัน bot detection ของ X
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    # รองรับการใช้ Chrome User Data Directory เพื่อใช้ session ที่ล็อกอินค้างไว้ (X มักบล็อกเนื้อหาถ้าไม่ได้ล็อกอิน)
    user_data_dir = os.getenv("CHROME_USER_DATA_DIR", "")
    profile_dir = os.getenv("CHROME_PROFILE_DIR", "")
    if user_data_dir:
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        if profile_dir:
            chrome_options.add_argument(f"--profile-directory={profile_dir}")

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
    chrome_options.add_argument(f"user-agent={user_agent}")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
            """
        }
    )
    return driver


def dismiss_x_popup(driver: webdriver.Chrome):
    """
    ปิด Popup Login / Sign up Sheet และ Dialog บังหน้าจอบน X
    """
    try:
        xpaths = [
            "//div[@data-testid='sheetDialog']//div[@aria-label='Close']",
            "//div[@data-testid='sheetDialog']//div[@aria-label='ปิด']",
            "//div[@role='dialog']//div[@aria-label='Close']",
            "//div[@role='dialog']//div[@aria-label='ปิด']",
            "//button[@aria-label='Close']",
            "//button[@data-testid='app-bar-close']",
        ]
        for xpath in xpaths:
            try:
                close_buttons = driver.find_elements(By.XPATH, xpath)
                for close_btn in close_buttons:
                    if close_btn.is_displayed():
                        driver.execute_script("arguments[0].click();", close_btn)
                        time.sleep(0.2)
            except Exception:
                pass

        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass
    except Exception:
        pass


def clean_x_url(url: str) -> str:
    """
    จัดรูปแบบ URL ของ X (สถานะ / ไลฟ์บรอดแคสต์) ให้สะอาดและเป็นมาตรฐาน
    """
    if not url:
        return ""

    bc_match = re.search(r"/i/broadcasts/(\w+)", url)
    if bc_match:
        return f"https://x.com/i/broadcasts/{bc_match.group(1)}"

    status_match = re.search(r"(?:x\.com|twitter\.com)/([^/]+)/status/(\d+)", url)
    if status_match:
        return f"https://x.com/{status_match.group(1)}/status/{status_match.group(2)}"

    return url.split("?")[0].rstrip("/")


def extract_thai_date_from_title(title: str) -> Optional[Tuple[int, int, Optional[int]]]:
    """
    ดึงวันที่ไทยจาก Title/ข้อความโพสต์ เช่น '(7 ส.ค. 69)', '7 ส.ค. 69'

    โพสต์ของ ThaiPBS มักจะมีวันที่ของเนื้อหาข่าวปนอยู่กลางข้อความด้วย (เช่น 'ก่อนเปิดเรียน 17 ส.ค.')
    ซึ่งไม่ใช่วันที่ของโพสต์จริง ส่วนวันที่ของโพสต์จริงจะอยู่ในวงเล็บท้ายข้อความเสมอ (เช่น '(10 ส.ค. 69)')
    จึงต้องหาวันที่แบบมีวงเล็บก่อน ถ้าไม่เจอค่อย fallback ไปหาวันที่แบบไม่มีวงเล็บ
    """
    if not title:
        return None

    month_regex = r"(?:ม\.ค\.?|ก\.พ\.?|มี\.ค\.?|เม\.ย\.?|พ\.ค\.?|มิ\.ย\.?|ก\.ค\.?|ส\.ค\.?|ก\.ย\.?|ต\.ค\.?|พ\.ย\.?|ธ\.ค\.?)"
    bracketed_pattern = rf"\(\s*(\d{{1,2}})\s*({month_regex})(?:\s*(\d{{2,4}}))?\s*\)"
    bare_pattern = rf"(\d{{1,2}})\s*({month_regex})(?:\s*(\d{{2,4}}))?"

    match = re.search(bracketed_pattern, title) or re.search(bare_pattern, title)
    if match:
        day_str = match.group(1)
        month_str = match.group(2).strip()
        year_str = match.group(3)

        day = int(day_str)
        month = THAI_MONTH_TO_INT.get(month_str, 0)
        year = int(year_str) if year_str else None

        if month > 0 and 1 <= day <= 31:
            return (day, month, year)

    return None


def scrape_x_live_videos(page_url: str, max_scrolls: int = 3, load_wait_seconds: int = 5) -> List[Dict[str, str]]:
    """
    Crawl หน้าโปรไฟล์หลักของ X (เช่น https://x.com/x_account_name)
    เพื่อหาลิงก์ไลฟ์บรอดแคสต์ (Broadcast link)

    หมายเหตุ: ในโหมดไม่ได้ล็อกอิน (logged-out, ไม่ได้ตั้งค่า CHROME_USER_DATA_DIR) X จะไม่โหลดโพสต์เพิ่มเติม
    ให้ต่อให้เลื่อนหน้าจอกี่ครั้งก็ตาม - จะเห็นแค่โพสต์ล่าสุดประมาณ 4-5 โพสต์เท่านั้น (ต่างจากตอนล็อกอิน
    ที่จะ infinite scroll โหลดเพิ่มเรื่อยๆ) จึงเลื่อนแค่ไม่กี่ครั้งและหยุดทันทีที่ความสูงหน้าเว็บไม่เพิ่มขึ้นแล้ว
    """
    driver = create_driver(headless=True)
    video_dict: Dict[str, Dict[str, str]] = {}

    try:
        print(f"[X Crawler] กำลังเปิดหน้าเว็บ: {page_url}")
        driver.get(page_url)

        print(f"[X Crawler] รอให้หน้าเว็บโหลดเนื้อหา ({load_wait_seconds} วินาที)...")
        time.sleep(load_wait_seconds)
        dismiss_x_popup(driver)

        # เลื่อนหน้าจอลงเล็กน้อยเพื่อ trigger lazy-load ของโพสต์ที่มีอยู่แล้ว (ไม่ใช่เพื่อโหลดโพสต์เพิ่ม)
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(max_scrolls):
            driver.execute_script("window.scrollBy(0, 1200); window.dispatchEvent(new Event('scroll'));")
            time.sleep(1.0)
            dismiss_x_popup(driver)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        extracted_data = driver.execute_script("""
            let results = [];

            // ลิงก์ Broadcast (การ์ดไลฟ์ / บันทึกการถ่ายทอดสด)
            // โหมดไม่ล็อกอิน: การ์ดเรนเดอร์เป็น <a aria-label="Open broadcast: ..." href="https://x.com/i/broadcasts/..."
            //   class="absolute inset-0"> คลุมทับการ์ดทั้งใบ ไม่มี innerText แต่ชื่อโพสต์เต็มๆอยู่ใน aria-label แทน
            // โหมดล็อกอิน: ลิงก์แบบเดียวกันนี้จะอยู่ภายใน <article data-testid="tweet">
            let broadcastLinks = Array.from(document.querySelectorAll('a[href*="/i/broadcasts/"]'));
            for (let a of broadcastLinks) {
                let ariaLabel = (a.getAttribute('aria-label') || '').trim();
                let container = a.closest('article') || a.closest('div[data-testid]') || a.parentElement || a;
                let txt = (ariaLabel || container.innerText || a.innerText || '').replace(/\\n+/g, ' ').trim();
                // ตัดคำนำหน้า "Open broadcast: " ออกจาก aria-label ให้เหลือแต่ข้อความโพสต์จริงสำหรับจับคู่ keyword
                txt = txt.replace(/^Open broadcast:\\s*/i, '');
                results.push({ href: a.href, text: txt || 'LIVE' });
            }

            return results;
        """)

        for item in extracted_data:
            href = item.get("href", "")
            if not href:
                continue

            clean_url = clean_x_url(href)
            if not clean_url:
                continue

            raw_text = item.get("text", "").strip()
            raw_text = re.sub(r"\s+", " ", raw_text)

            id_match = re.search(r"/(?:status|broadcasts)/(\w+)", clean_url)
            canonical_key = id_match.group(1) if id_match else clean_url

            if canonical_key in video_dict:
                if len(raw_text) > len(video_dict[canonical_key]["title"]):
                    video_dict[canonical_key]["title"] = raw_text
                    video_dict[canonical_key]["raw_text"] = raw_text
                    video_dict[canonical_key]["url"] = clean_url
            else:
                video_dict[canonical_key] = {
                    "title": raw_text,
                    "url": clean_url,
                    "raw_text": raw_text
                }

        videos = list(video_dict.values())
        return videos

    finally:
        driver.quit()


def normalize_title_text(text: str) -> str:
    """
    ปรับรูปแบบข้อความให้อยู่ในรูปมาตรฐานสำหรับจับคู่ (ตัด space, hashtag, วงเล็บ)
    """
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"\(.*?\)", "", t)
    t = t.replace("็", "๊")
    t = re.sub(r"[#\s\.\-:_’'\"!]", "", t)
    return t.lower()


def find_matching_x_video(
    videos: List[Dict[str, str]],
    program_title: str,
    broadcast_time: Optional[str] = None,
    broadcast_date: Optional[str] = None,
    scheduled_dt: Optional[datetime] = None
) -> Optional[Dict[str, str]]:
    """
    ค้นหาวิดีโอ/บรอดแคสต์บน X ที่ตรงกับชื่อรายการ (Column C)

    เนื่องจากในโหมดไม่ล็อกอินจะเห็นโพสต์ล่าสุดแค่ 4-5 โพสต์ (videos เรียงจากใหม่ไปเก่าตามลำดับที่ scrape ได้
    จากหน้าเว็บ) จึงไล่ตรวจสอบทีละโพสต์ตามลำดับนั้น แล้วคืนค่า "โพสต์แรกที่ตรงเงื่อนไข" ทันที แทนที่จะคำนวณ
    คะแนนเพื่อหาโพสต์ที่ตรงที่สุด:
    1. หากมีวันที่ระบุอยู่ในข้อความโพสต์ ต้องตรงกับ scheduled_dt เท่านั้น (ไม่ตรง -> ปฏิเสธ)
    2. ชื่อรายการหรือ Keyword สำคัญต้องปรากฏในข้อความโพสต์ (ลองแบบเข้มงวดกับทุกโพสต์ก่อน
       ถ้าไม่มีโพสต์ไหนผ่านเลย ค่อยลองแบบผ่อนปรนกับทุกโพสต์อีกรอบ)
    """
    if not program_title or not videos:
        return None

    raw_title = program_title.strip()
    clean_search_title = normalize_title_text(raw_title)
    if not clean_search_title:
        return None

    all_words = [w for w in re.split(r"[\s#\(\)\-_]+", raw_title) if w]
    sig_words = [w for w in all_words if len(w) > 1 and normalize_title_text(w) not in COMMON_STOPWORDS]
    if not sig_words:
        sig_words = all_words

    def passes_date_filter(card_text: str) -> bool:
        if not scheduled_dt:
            return True
        post_date = extract_thai_date_from_title(card_text)
        if post_date is None:
            return True
        v_day, v_month, v_year = post_date
        if v_day != scheduled_dt.day or v_month != scheduled_dt.month:
            return False
        if v_year is not None and (v_year % 100) != ((scheduled_dt.year + 543) % 100):
            return False
        return True

    def strict_match(norm_card_text: str) -> bool:
        if clean_search_title in norm_card_text:
            return True
        matched_sig = [w for w in sig_words if normalize_title_text(w) in norm_card_text]
        return bool(sig_words) and len(matched_sig) >= len(sig_words)

    def loose_match(norm_card_text: str) -> bool:
        matched_sig = [w for w in sig_words if normalize_title_text(w) in norm_card_text]
        return len(sig_words) > 1 and len(matched_sig) >= max(1, len(sig_words) - 1)

    for matcher in (strict_match, loose_match):
        for video in videos:
            card_text = video.get("title", "")
            if not passes_date_filter(card_text):
                continue
            if matcher(normalize_title_text(card_text)):
                return video

    return None
