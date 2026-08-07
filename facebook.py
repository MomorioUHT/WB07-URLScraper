import os
import re
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

# ตารางชื่อเดือนภาษาไทยแบบย่อ
THAI_MONTHS_SHORT = {
    1: "ม.ค.", 2: "ก.พ.", 3: "มี.ค.", 4: "เม.ย.",
    5: "พ.ค.", 6: "มิ.ย.", 7: "ก.ค.", 8: "ส.ค.",
    9: "ก.ย.", 10: "ต.ค.", 11: "พ.ย.", 12: "ธ.ค."
}

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

COMMON_STOPWORDS = {"ไทยพีบีเอส", "thaipbs", "live", "สด", "น", "recap", "hd", "ช่อง", "หมายเลข3"}


def create_driver(headless: bool = True) -> webdriver.Chrome:
    """
    สร้างและตั้งค่า Selenium Chrome WebDriver พร้อม Stealth Arguments
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
    
    # ป้องกัน bot detection ของ Facebook
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    # รองรับการใช้ Chrome User Data Directory เพื่อใช้ session ที่ล็อกอินค้างไว้
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


def dismiss_login_popup(driver: webdriver.Chrome):
    """
    ปิด Popup Login Modal และ Dialog บังหน้าจอ
    """
    try:
        dialogs = driver.find_elements(By.XPATH, "//div[@role='dialog']")
        if dialogs:
            xpaths = [
                "//div[@role='dialog']//div[@aria-label='Close']", 
                "//div[@role='dialog']//div[@aria-label='ปิด']", 
                "//div[@aria-label='Close']", 
                "//div[@aria-label='ปิด']",
                "//div[@role='dialog']//*[@role='button']",
                "//div[@role='banner']//*[@role='button']",
                "//div[@role='dialog']//i"
            ]
            for xpath in xpaths:
                try:
                    close_buttons = driver.find_elements(By.XPATH, xpath)
                    for close_btn in close_buttons:
                        if close_btn.is_displayed():
                            driver.execute_script("arguments[0].click();", close_btn)
                            time.sleep(0.2)
                            break
                except Exception:
                    pass

        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass

        # Cleanup Dialog & Overlays
        js_cleanup = """
        let dialogs = document.querySelectorAll("div[role='dialog']");
        dialogs.forEach(d => d.remove());
        let overlays = document.querySelectorAll("div[data-nosnippet]");
        overlays.forEach(o => o.remove());
        document.body.style.overflow = 'auto';
        document.documentElement.style.overflow = 'auto';
        """
        driver.execute_script(js_cleanup)
    except Exception:
        pass


def take_screenshot(driver: webdriver.Chrome, prefix: str = "facebook_live") -> str:
    """
    บันทึกภาพหน้าจอ (Screenshot) ลงในโฟลเดอร์ screenshots
    """
    screenshot_dir = os.path.join(os.getcwd(), "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}.png"
    filepath = os.path.join(screenshot_dir, filename)
    
    driver.save_screenshot(filepath)
    latest_path = os.path.join(screenshot_dir, f"{prefix}_latest.png")
    driver.save_screenshot(latest_path)
    
    print(f"[Screenshot] บันทึกภาพหน้าจอไว้ที่: {filepath}")
    return filepath


def clean_facebook_url(url: str) -> str:
    """
    จัดรูปแบบ URL วิดีโอ Facebook ให้สะอาดและเป็นมาตรฐาน
    """
    if not url:
        return ""
    
    if "/watch" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return f"https://www.facebook.com/watch/?v={qs['v'][0]}"
            
    vid_match = re.search(r"/videos/(?:[^/]+/)?(\d{10,20})", url)
    if vid_match:
        vid_id = vid_match.group(1)
        page_match = re.search(r"facebook\.com/([^/]+)/videos", url)
        page_name = page_match.group(1) if page_match and page_match.group(1) not in ("watch", "videos") else ""
        if page_name and not page_name.isdigit():
            return f"https://www.facebook.com/{page_name}/videos/{vid_id}/"
        return f"https://www.facebook.com/watch/?v={vid_id}"
        
    return url.split("?")[0].rstrip("/") + "/"


def extract_thai_date_from_title(title: str) -> Optional[Tuple[int, int, Optional[int]]]:
    """
    ดึงวันที่ไทยจาก Title เช่น:
    - '(7 ส.ค. 69)' -> (7, 8, 69)
    - '(7 ส.ค.69)'  -> (7, 8, 69)
    - '(7 ส.ค.)'    -> (7, 8, None)
    - '6 ส.ค. 69'   -> (6, 8, 69)
    """
    if not title:
        return None
        
    # ค้นหา patterns วันที่ เช่น (7 ส.ค. 69), (7 ส.ค.69), 7 ส.ค. 69, 7 ส.ค.
    month_regex = r"(?:ม\.ค\.?|ก\.พ\.?|มี\.ค\.?|เม\.ย\.?|พ\.ค\.?|มิ\.ย\.?|ก\.ค\.?|ส\.ค\.?|ก\.ย\.?|ต\.ค\.?|พ\.ย\.?|ธ\.ค\.?)"
    pattern = rf"\(?\s*(\d{{1,2}})\s*({month_regex})(?:\s*(\d{{2,4}}))?\s*\)?"
    
    match = re.search(pattern, title)
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


def scrape_live_videos(page_url: str = "https://www.facebook.com/watch/ThaiPBS/", max_scrolls: int = 20, load_wait_seconds: int = 5) -> List[Dict[str, str]]:
    """
    Crawl ข้อมูลวิดีโอจากหน้า Facebook Watch Grid
    """
    driver = create_driver(headless=True)
    video_dict: Dict[str, Dict[str, str]] = {}
    
    try:
        print(f"[Facebook Crawler] กำลังเปิดหน้าเว็บ: {page_url}")
        driver.get(page_url)
        
        # 1. รอให้หน้าเว็บโหลด
        print(f"[Facebook Crawler] รอให้หน้าเว็บโหลดเนื้อหา ({load_wait_seconds} วินาที)...")
        time.sleep(load_wait_seconds)
        dismiss_login_popup(driver)
        take_screenshot(driver, prefix="01_page_loaded")
        
        # 2. เลื่อนหน้าจอลงเพื่อโหลดวิดีโอใน Grid แบบ Deep Scroll
        for i in range(max_scrolls):
            driver.execute_script("""
                document.querySelectorAll('div[role="dialog"]').forEach(el => el.remove());
                document.querySelectorAll('div[data-nosnippet="true"]').forEach(el => el.remove());
                
                document.documentElement.style.setProperty('overflow', 'auto', 'important');
                document.documentElement.style.setProperty('overflow-y', 'auto', 'important');
                document.body.style.setProperty('overflow', 'auto', 'important');
                document.body.style.setProperty('overflow-y', 'auto', 'important');
            """)
            
            # เลื่อนลงทีละช่วง
            driver.execute_script("""
                window.scrollBy(0, 1500);
                window.dispatchEvent(new Event('scroll'));
            """)
            time.sleep(1.0)
            dismiss_login_popup(driver)
            
        take_screenshot(driver, prefix="02_after_scroll")
        
        # 3. ดึงข้อมูลวิดีโอทั้งหมดจาก Grid/Feed บนหน้า Watch
        extracted_data = driver.execute_script("""
            let allLinks = Array.from(document.querySelectorAll('a[href*="/videos/"], a[href*="/watch/"], a[href*="v="]'));
            let results = [];
            let mainEl = document.querySelector('div[role="main"]') || document.body;
            
            // 3.2 ดึง Past live videos cards แต่ละการ์ดอย่างแม่นยำ (ไม่ดึง main container ทั้งหน้า)
            let gridLinks = Array.from(document.querySelectorAll('a[href*="/videos/"], a[href*="/watch/"]'));
            for (let a of gridLinks) {
                let href = a.href;
                if (href.includes('comment_id')) continue;
                
                // หา card container ที่เล็กที่สุดของการ์ดนั้นๆ
                let card = a;
                let cardText = '';
                while (card && card !== mainEl && card.tagName !== 'BODY') {
                    let txt = (card.innerText || '').replace(/\\n+/g, ' ').trim();
                    if (txt.length >= 15 && txt.length <= 300 && (txt.includes('Live') || txt.includes('น.') || txt.includes('#') || txt.includes(':') || txt.includes('views') || txt.includes('รับชม'))) {
                        cardText = txt;
                        break;
                    }
                    card = card.parentElement;
                }
                
                if (!cardText) {
                    let aria = a.getAttribute('aria-label') || '';
                    let aText = a.innerText.replace(/\\n+/g, ' ').trim();
                    cardText = (aria + ' ' + aText).trim();
                }
                
                results.push({
                    href: href,
                    text: cardText
                });
            }
            
            return results;
        """)
        
        for item in extracted_data:
            try:
                href = item.get("href", "")
                if not href or "comment_id" in href:
                    continue
                    
                clean_url = clean_facebook_url(urljoin("https://www.facebook.com", href))
                if not clean_url or ("/videos/" not in clean_url and "/watch" not in clean_url and "/live" not in clean_url):
                    continue
                
                raw_text = item.get("text", "").strip()
                raw_text = re.sub(r"\s+", " ", raw_text)
                
                # สกัด Video ID เพื่อรวมลิงก์ที่เป็นวิดีโอเดียวกัน (Deduplicate by Video ID)
                vid_match = re.search(r"/videos/(\d+)", clean_url)
                canonical_key = vid_match.group(1) if vid_match else clean_url
                
                if canonical_key in video_dict:
                    current_title = video_dict[canonical_key]["title"]
                    # อัปเดต Title ถ้าเจอข้อความที่ละเอียดกว่า หรือมีคำว่า Live / ชื่อรายการ / วันที่
                    if len(raw_text) > len(current_title) or (("Live" in raw_text or "น." in raw_text or "ส.ค." in raw_text) and "Live" not in current_title):
                        video_dict[canonical_key]["title"] = raw_text
                        video_dict[canonical_key]["raw_text"] = raw_text
                        video_dict[canonical_key]["url"] = clean_url
                else:
                    video_dict[canonical_key] = {
                        "title": raw_text,
                        "url": clean_url,
                        "raw_text": raw_text
                    }
            except Exception:
                continue

        videos = list(video_dict.values())
        print(f"\n[Facebook Crawler] ดึงรายการวิดีโอจากหน้าเว็บได้ทั้งหมด {len(videos)} รายการ:")
        for idx, v in enumerate(videos, start=1):
            title_preview = v['title'][:80]
            print(f"  {idx}. {title_preview}... -> {v['url']}")
            
        return videos
        
    finally:
        driver.quit()


def normalize_title_text(text: str) -> str:
    """
    ปรับรูปแบบข้อความให้อยู่ในรูปมาตรฐานสำหรับจับคู่ (ตัด space, hashtag, วงเล็บ)
    เช่น:
    - 'วันใหม่  ไทยพีบีเอส' -> 'วันใหม่ไทยพีบีเอส'
    - '#วันใหม่ไทยพีบีเอส'  -> 'วันใหม่ไทยพีบีเอส'
    - 'ป็อป ดีโคตร (Pop-D’Code)' -> 'ป๊อปดีโคตร'
    """
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"\(.*?\)", "", t)
    t = t.replace("็", "๊")
    t = re.sub(r"[#\s\.\-:_’'\"!]", "", t)
    return t.lower()


def find_matching_video(
    videos: List[Dict[str, str]], 
    program_title: str, 
    broadcast_time: Optional[str] = None, 
    broadcast_date: Optional[str] = None,
    scheduled_dt: Optional[datetime] = None
) -> Optional[Dict[str, str]]:
    """
    ค้นหาวิดีโอ Facebook ที่ตรงกับชื่อรายการ (Column C)
    กฎเกณฑ์การจับคู่:
    1. ตรวจสอบ 'วันที่' (เช่น '(7 ส.ค. 69)' หรือ '(6 ส.ค. 69)') ต้องตรงกับวันที่ที่ต้องการค้นหา (scheduled_dt) อย่างเคร่งครัด
       หาก Title ของวิดีโอบน Facebook มีวันที่ระบุอยู่แล้วไม่ตรงกัน จะถูกปฏิเสธทันที (ไม่ดึงข้ามวัน)
    2. ตรวจสอบชื่อรายการ (Title Matching): ชื่อรายการหรือ Keyword สำคัญต้องปรากฏในการ์ดวิดีโอ
    3. ตรวจสอบเวลาออกอากาศ (เช่น 10:00, 10.30 น.)
    """
    if not program_title or not videos:
        return None
        
    raw_title = program_title.strip()
    clean_search_title = normalize_title_text(raw_title)
    if not clean_search_title:
        return None

    # ตัด Stopwords ทั่วไปออก เช่น 'ไทยพีบีเอส', 'live'
    all_words = [w for w in re.split(r"[\s#\(\)\-_]+", raw_title) if w]
    sig_words = [w for w in all_words if len(w) > 1 and normalize_title_text(w) not in COMMON_STOPWORDS]
    if not sig_words:
        sig_words = all_words

    # เวลาที่ต้องการค้นหา
    time_regex = None
    if broadcast_time:
        t_clean = broadcast_time.strip().replace("น.", "").replace("น", "").strip()
        if "-" in t_clean:
            t_clean = t_clean.split("-")[0].strip()
        t_clean = t_clean.replace(":", ".").strip()
        parts = t_clean.split(".")
        if len(parts) >= 2:
            h = int(parts[0])
            m = parts[1]
            time_regex = re.compile(rf"(?:0?{h})[.:]{m}", re.IGNORECASE)

    best_match = None
    highest_score = 0

    for video in videos:
        card_text = video.get("title", "")
        norm_card_text = normalize_title_text(card_text)
        
        # 1. ตรวจสอบวันที่ (Strict Date Verification)
        if scheduled_dt:
            sched_day = scheduled_dt.day
            sched_month = scheduled_dt.month
            sched_year_be = (scheduled_dt.year + 543) % 100  # เช่น 2569 -> 69
            
            video_date = extract_thai_date_from_title(card_text)
            if video_date is not None:
                v_day, v_month, v_year = video_date
                # หากวัน หรือ เดือนไม่ตรงกัน -> ปฏิเสธทันที (ห้ามดึงข้ามวัน)
                if v_day != sched_day or v_month != sched_month:
                    continue
                    
                # หากระบุปีแล้วปีไม่ตรงกัน -> ปฏิเสธ
                if v_year is not None:
                    v_year_2digit = v_year % 100
                    if v_year_2digit != sched_year_be:
                        continue

        # 2. ตรวจสอบชื่อรายการ (Title Matching MUST succeed)
        title_matched = False
        title_score = 0
        
        if clean_search_title in norm_card_text:
            title_matched = True
            title_score = 30
        else:
            matched_sig = [w for w in sig_words if normalize_title_text(w) in norm_card_text]
            if len(sig_words) == 1 and matched_sig:
                title_matched = True
                title_score = 25
            elif len(sig_words) > 1 and len(matched_sig) >= len(sig_words):
                title_matched = True
                title_score = 25
            elif len(sig_words) > 1 and len(matched_sig) >= max(1, len(sig_words) - 1):
                title_matched = True
                title_score = 15
                
        # หากชื่อรายการไม่ตรงเลย ข้ามไป (ไม่จับคู่มั่ว)
        if not title_matched:
            continue
            
        score = title_score
        
        # 3. ตรวจสอบเวลาออกอากาศ (+10 คะแนน)
        if time_regex and time_regex.search(card_text):
            score += 10
            
        if score > highest_score:
            highest_score = score
            best_match = video

    return best_match
