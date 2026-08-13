import os
import re
import subprocess
import sys
import time
from typing import Optional, Tuple

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options

# รองรับการแสดงผลภาษาไทยบน Windows Terminal ที่ default console codepage ไม่ใช่ UTF-8 (เช่น
# cp1252/cp874 บางเครื่อง) หากไม่ทำ ทุก print() ที่มีข้อความไทยปนอยู่ในไฟล์นี้และไฟล์ที่ import
# โมดูลนี้ (facebook.py, youtube.py, x.py, login_facebook.py, logout_facebook.py) จะพังด้วย
# UnicodeEncodeError ทันทีที่ error จริงเกิดขึ้น กลบข้อความ error ตัวจริงจนไม่เหลือร่องรอยให้ดู
# (linkcrawler.py มี guard เดียวกันนี้อยู่แล้ว แต่ทำซ้ำที่นี่เพื่อให้ครอบคลุมทุก Entry Point)
for _stream in (sys.stdout, sys.stderr):
    if getattr(_stream, "encoding", None) != "utf-8":
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

# ไดเรกทอรีเก็บ Chrome User Profile ที่ล็อกอิน Facebook ค้างไว้ (สร้าง/ล้างข้อมูลผ่าน
# login_facebook.py / logout_facebook.py) ใช้ร่วมกันทุกโมดูลที่เรียก
# create_stealth_chrome_driver() (facebook.py, x.py, youtube.py) เพื่อให้เห็นวิดีโอ Live ที่
# ต้องล็อกอินบัญชี Facebook ก่อนถึงจะดูได้
#
# ตั้งใจเก็บไว้นอกโฟลเดอร์โปรเจกต์ (เช่น %LOCALAPPDATA%\LinkScraperAutomate บน Windows) แทนที่จะ
# เก็บไว้ใต้ตัวโปรเจกต์เอง เพราะโปรเจกต์นี้มักถูก clone ไว้ใต้ Desktop\...\WB-07-LinkScraperAutomate
# ซึ่ง path ยาวอยู่แล้ว โดยเฉพาะเครื่องที่ Desktop ถูก OneDrive sync ไว้ (เติม
# "OneDrive - ชื่อบริษัท\Desktop\" นำหน้า) ทำให้ path เต็มของไฟล์ลึกๆที่ Chrome สร้างขึ้นเอง เช่น
# Default\Service Worker\CacheStorage\<hash>\... ทะลุขีดจำกัด Windows MAX_PATH (260 ตัวอักษร)
# แล้วเปิด Chrome ไม่ขึ้นด้วย error "session not created: from unknown error: failed to write
# prefs file" (พังเฉพาะบางเครื่องที่ path ยาวเกิน แม้โค้ดจะเหมือนกันทุกเครื่องก็ตาม)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or PROJECT_ROOT,
    "LinkScraperAutomate",
)
FACEBOOK_PROFILE_DIR = os.path.join(CHROME_DATA_DIR, "facebook_profile")

# ไฟล์ Lock ที่ Chrome สร้างไว้ระหว่างใช้ Profile นี้อยู่ (กลไกนี้เป็นของ Linux/Mac เท่านั้น
# Windows ไม่สร้างไฟล์เหล่านี้ แต่ยังคงลบทิ้งไว้เผื่อรันข้าม OS) หาก Chrome ปิดไม่สนิท (ปิดหน้าต่าง
# เอง แทนกด Enter ให้ driver.quit() ทำงาน, เครื่องแฮงค์/ไฟดับ) ไฟล์เหล่านี้จะค้างอยู่ และทำให้เปิด
# Chrome ครั้งถัดไปด้วย user-data-dir เดียวกันไม่ขึ้น (session not created: user data directory
# is already in use) จึงต้องล้างทิ้งก่อนเปิด driver ทุกครั้ง
PROFILE_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")

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


def _kill_orphaned_chrome_processes_windows() -> None:
    """
    Windows ไม่ใช้ไฟล์ Lock แบบ Linux/Mac (SingletonLock ฯลฯ) แต่ล็อก Profile ด้วย process ที่ยัง
    เปิดค้างอยู่จริงแทน (เช่น Chrome จากรอบก่อนที่ driver.quit() ไม่ทันทำงาน, Python ถูกปิดกลางคัน)
    จึงต้องค้นหา chrome.exe/chromedriver.exe ที่ Command Line อ้างอิงถึง FACEBOOK_PROFILE_DIR
    นี้โดยเฉพาะ (ไม่แตะ Chrome browser ปกติของผู้ใช้ที่เปิดอยู่) แล้วปิดทิ้งก่อนเปิด driver ใหม่
    เป็น Best Effort ล้วนๆ หากค้นหา/ปิดไม่สำเร็จ (เช่น powershell ใช้งานไม่ได้) จะข้ามไปเงียบๆ
    """
    ps_script = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='chromedriver.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{FACEBOOK_PROFILE_DIR}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass


def _clear_stale_profile_locks() -> None:
    """
    ล้างสถานะ Chrome Profile ที่อาจค้างจากการปิด Chrome ไม่สนิทในรอบก่อนหน้า ป้องกัน error
    'user data directory is already in use' ตอนเปิด Chrome ครั้งถัดไปด้วย Profile เดียวกัน
    """
    for filename in PROFILE_LOCK_FILES:
        lock_path = os.path.join(FACEBOOK_PROFILE_DIR, filename)
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except OSError:
            pass

    if os.name == "nt":
        _kill_orphaned_chrome_processes_windows()


def _build_chrome_options(headless: bool) -> Options:
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

    chrome_options.add_argument(f"--user-data-dir={FACEBOOK_PROFILE_DIR}")

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
    chrome_options.add_argument(f"user-agent={user_agent}")
    return chrome_options


def create_stealth_chrome_driver(headless: bool = True) -> webdriver.Chrome:
    """
    สร้างและตั้งค่า Selenium Chrome WebDriver พร้อม Stealth Arguments
    (ป้องกัน bot detection) ใช้ร่วมกันสำหรับหน้าเว็บที่ตรวจจับ automation เช่น Facebook, X, YouTube
    ใช้ Chrome User Data Directory ที่ chrome_data/facebook_profile เสมอ เพื่อคง session ที่
    ล็อกอิน Facebook ค้างไว้ (สร้างผ่าน login_facebook.py) ให้เห็นวิดีโอ Live ที่ต้องล็อกอิน
    บัญชี Facebook ก่อนถึงจะดูได้

    ไม่ระบุ Service/executable_path เอง แต่ปล่อยให้ Selenium Manager (built-in ตั้งแต่ Selenium
    4.6 ขึ้นไป) เป็นผู้ดาวน์โหลด/เลือก ChromeDriver ที่ตรงกับเวอร์ชัน Chrome ที่ติดตั้งอยู่บนเครื่อง
    นั้นๆ ให้อัตโนมัติ แทนที่จะใช้ webdriver-manager ซึ่งบาง cache เวอร์ชันเก่าบนเครื่องอื่นอาจไม่
    ตรงกับ Chrome ที่ติดตั้งจริง ทำให้เปิด Chrome ไม่ขึ้น

    หากเปิด Chrome ไม่สำเร็จ (เช่น Profile ถูก Lock ค้างจากครั้งก่อน) จะล้าง Lock File แล้วลองใหม่
    อีก 1 ครั้งก่อนจะโยน Exception ออกไปจริงๆ พร้อม log รายละเอียดให้เห็นสาเหตุชัดเจน
    """
    os.makedirs(FACEBOOK_PROFILE_DIR, exist_ok=True)

    max_attempts = 2
    last_error: Optional[WebDriverException] = None

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            _clear_stale_profile_locks()
        try:
            driver = webdriver.Chrome(options=_build_chrome_options(headless))
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
        except WebDriverException as e:
            last_error = e
            print(f"[Chrome Driver] เปิด Chrome ไม่สำเร็จ (ครั้งที่ {attempt}/{max_attempts}): {e}")
            if attempt < max_attempts:
                print("[Chrome Driver] กำลังล้าง Lock File ของ Profile แล้วลองเปิด Chrome ใหม่อีกครั้ง...")
                time.sleep(2)

    print(f"[Chrome Driver] เปิด Chrome ไม่สำเร็จหลังลองครบ {max_attempts} ครั้งแล้ว ยอมแพ้")
    raise last_error
