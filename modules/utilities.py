import os
import re
from typing import Optional, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ไดเรกทอรีเก็บ Chrome User Profile ที่ล็อกอิน Facebook ค้างไว้ (สร้าง/ล้างข้อมูลผ่าน
# login_facebook.py / logout_facebook.py ที่ root ของโปรเจกต์) ใช้ร่วมกันทุกโมดูลที่เรียก
# create_stealth_chrome_driver() (facebook.py, x.py, youtube.py) เพื่อให้เห็นวิดีโอ Live ที่
# ต้องล็อกอินบัญชี Facebook ก่อนถึงจะดูได้
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME_DATA_DIR = os.path.join(PROJECT_ROOT, "chrome_data")
FACEBOOK_PROFILE_DIR = os.path.join(CHROME_DATA_DIR, "facebook_profile")

# ตารางแปลงชื่อเดือนภาษาไทย (แบบย่อและเต็ม) เป็นตัวเลข (1-12)
# ใช้ร่วมกันระหว่าง facebook.py, youtube.py และ x.py
THAI_MONTH_TO_INT = {
    "ม.ค.": 1, "ม.ค": 1, "มกราคม": 1,
    "ก.พ.": 2, "ก.พ": 2, "กุมภาพันธ์": 2,
    "มี.ค.": 3, "มี.ค": 3, "มีนาคม": 3,
    "เม.ย.": 4, "เม.ย": 4, "เมษายน": 4,
    "พ.ค.": 5, "พ.ค": 5, "พฤษภาคม": 5,
    "มิ.ย.": 6, "มิ.ย": 6, "มิถุนายน": 6,
    "ก.ค.": 7, "ก.ค": 7, "กรกฎาคม": 7,
    "ส.ค.": 8, "ส.ค": 8, "สิงหาคม": 8,
    "ก.ย.": 9, "ก.ย": 9, "กันยายน": 9,
    "ต.ค.": 10, "ต.ค": 10, "ตุลาคม": 10,
    "พ.ย.": 11, "พ.ย": 11, "พฤศจิกายน": 11,
    "ธ.ค.": 12, "ธ.ค": 12, "ธันวาคม": 12,
}

# Regex สำหรับจับชื่อเดือนภาษาไทยแบบย่อ (เช่น 'ส.ค.', 'ส.ค')
THAI_MONTH_REGEX = (
    r"(?:ม\.ค\.?|ก\.พ\.?|มี\.ค\.?|เม\.ย\.?|พ\.ค\.?|มิ\.ย\.?"
    r"|ก\.ค\.?|ส\.ค\.?|ก\.ย\.?|ต\.ค\.?|พ\.ย\.?|ธ\.ค\.?)"
)


def parse_thai_date_match(match: Optional[re.Match], normalize_short_year: bool = False) -> Optional[Tuple[int, int, Optional[int]]]:
    """
    แปลงผลลัพธ์จาก re.search (ที่ match ด้วย pattern รูปแบบ 'วัน เดือน ปี') ให้เป็น (day, month, year)
    - normalize_short_year: หากปีที่ดึงได้เป็น พ.ศ. เต็ม (เช่น 2569) ให้ตัดเหลือ 2 หลักท้าย (69)
    คืนค่า None หากไม่มี match หรือเดือน/วันไม่ถูกต้อง
    """
    if not match:
        return None

    day = int(match.group(1))
    month_str = match.group(2).strip()
    year_str = match.group(3)

    month = THAI_MONTH_TO_INT.get(month_str, 0)
    year = None
    if year_str:
        year = int(year_str)
        if normalize_short_year and year > 2500:
            year = year % 100

    if month > 0 and 1 <= day <= 31:
        return (day, month, year)

    return None


def gregorian_year_to_be_short(year: int) -> int:
    """
    แปลงปี ค.ศ. (Gregorian) เป็นปี พ.ศ. แบบ 2 หลักท้าย เช่น 2026 -> 69
    ใช้เทียบกับปีที่ดึงได้จาก Title บนหน้าเว็บ (ซึ่งมักแสดงเป็น พ.ศ. แบบย่อ)
    """
    return (year + 543) % 100


def normalize_title_text(text: str) -> str:
    """
    ปรับรูปแบบข้อความให้อยู่ในรูปมาตรฐานสำหรับจับคู่ (ตัด space, hashtag, วงเล็บ)
    เช่น:
    - 'วันใหม่  ไทยพีบีเอส' -> 'วันใหม่ไทยพีบีเอส'
    - '#วันใหม่ไทยพีบีเอส'  -> 'วันใหม่ไทยพีบีเอส'
    """
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"\(.*?\)", "", t)
    t = t.replace("็", "๊")
    t = re.sub(r"[#\s\.\-:_’'\"!]", "", t)
    return t.lower()


def create_stealth_chrome_driver(headless: bool = True) -> webdriver.Chrome:
    """
    สร้างและตั้งค่า Selenium Chrome WebDriver พร้อม Stealth Arguments
    (ป้องกัน bot detection) ใช้ร่วมกันสำหรับหน้าเว็บที่ตรวจจับ automation เช่น Facebook, X, YouTube
    ใช้ Chrome User Data Directory ที่ chrome_data/facebook_profile เสมอ เพื่อคง session ที่
    ล็อกอิน Facebook ค้างไว้ (สร้างผ่าน login_facebook.py) ให้เห็นวิดีโอ Live ที่ต้องล็อกอิน
    บัญชี Facebook ก่อนถึงจะดูได้
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

    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

    os.makedirs(FACEBOOK_PROFILE_DIR, exist_ok=True)
    chrome_options.add_argument(f"--user-data-dir={FACEBOOK_PROFILE_DIR}")

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
