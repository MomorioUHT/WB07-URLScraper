import os
import re
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ตารางแปลงชื่อเดือนภาษาไทยเป็นตัวเลข (1-12)
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

COMMON_STOPWORDS = {
    "thaipbs", "ไทยพีบีเอส", "live", "สด", "ถ่ายทอดสด", 
    "recap", "daily", "ตอนที่", "ep", "hd"
}


def create_driver(headless: bool = True) -> webdriver.Chrome:
    """
    สร้างและตั้งค่า Selenium WebDriver (Chrome) สำหรับ YouTube
    """
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    chrome_options.add_argument("--lang=th-TH,th")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(45)
    return driver


def clean_youtube_url(url: str) -> str:
    """
    จัดรูปแบบ URL วิดีโอ YouTube ให้สะอาดและเป็นมาตรฐาน
    เช่น:
    - https://www.youtube.com/watch?v=R2jQ48i9l40
    - https://youtu.be/R2jQ48i9l40 -> https://www.youtube.com/watch?v=R2jQ48i9l40
    """
    if not url:
        return ""
        
    if "youtu.be/" in url:
        vid_id = url.split("youtu.be/")[1].split("?")[0].split("&")[0]
        return f"https://www.youtube.com/watch?v={vid_id}"
        
    if "youtube.com/watch" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return f"https://www.youtube.com/watch?v={qs['v'][0]}"
            
    match = re.search(r"youtube\.com/live/([a-zA-Z0-9_\-]+)", url)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
        
    return url.split("&")[0]


def extract_thai_date_from_youtube_title(title: str) -> Optional[Tuple[int, int, Optional[int]]]:
    """
    ดึงวันที่ไทยจาก Title ของ YouTube Live
    โดย YouTube มักมีวันที่อยู่หลังเครื่องหมาย '|' เช่น:
    - '🔴 [Live] ทุกทิศทั่วไทย | 7 ส.ค. 69' -> (7, 8, 69)
    - '🔴 [Live] สถานีประชาชน | 7 ส.ค. 2569' -> (7, 8, 69)
    """
    if not title:
        return None
        
    # หากมีเครื่องหมาย | ให้เน้นดูข้อความหลัง |
    target_text = title
    if "|" in title:
        parts = title.split("|")
        target_text = parts[-1].strip()
        
    month_regex = r"(?:ม\.ค\.?|ก\.พ\.?|มี\.ค\.?|เม\.ย\.?|พ\.ค\.?|มิ\.ย\.?|ก\.ค\.?|ส\.ค\.?|ก\.ย\.?|ต\.ค\.?|พ\.ย\.?|ธ\.ค\.?)"
    pattern = rf"(\d{{1,2}})\s*({month_regex})(?:\s*(\d{{2,4}}))?"
    
    match = re.search(pattern, target_text)
    if not match and target_text != title:
        match = re.search(pattern, title)
        
    if match:
        day = int(match.group(1))
        month_str = match.group(2).strip()
        year_str = match.group(3)
        
        month = THAI_MONTH_TO_INT.get(month_str, 0)
        year = None
        if year_str:
            y_int = int(year_str)
            if y_int > 2500:
                y_int = y_int % 100
            year = y_int
            
        if month > 0 and 1 <= day <= 31:
            return (day, month, year)
            
    return None


def scrape_youtube_streams(
    channel_streams_url: str = "https://www.youtube.com/@ThaiPBS/streams", 
    max_scrolls: int = 15, 
    load_wait_seconds: int = 5
) -> List[Dict[str, str]]:
    """
    Crawl ข้อมูลวิดีโอจากหน้า YouTube Streams (@ThaiPBS/streams)
    ดึง Title และ URL ของ Live Streams ทั้งหมด
    """
    driver = create_driver(headless=True)
    video_dict: Dict[str, Dict[str, str]] = {}
    
    try:
        print(f"[YouTube Crawler] กำลังเปิดหน้าเว็บ: {channel_streams_url}")
        driver.get(channel_streams_url)
        
        print(f"[YouTube Crawler] รอให้หน้าเว็บโหลดเนื้อหา ({load_wait_seconds} วินาที)...")
        time.sleep(load_wait_seconds)
        
        # เลื่อนหน้าจอลงเพื่อโหลดวิดีโอ Streams เพิ่มเติม
        for i in range(max_scrolls):
            driver.execute_script("window.scrollBy(0, 1500);")
            time.sleep(0.8)
            
        extracted_data = driver.execute_script("""
            let results = [];
            let items = document.querySelectorAll('ytd-rich-item-renderer');
            for (let it of items) {
                let links = it.querySelectorAll('a[href*="/watch"]');
                let bestTitle = "";
                let bestHref = "";
                for (let a of links) {
                    let t = (a.innerText || a.textContent || "").trim();
                    // กรอง badge ตัวเลขเวลา / LIVE / สด / Upcoming ออก
                    if (t && !t.match(/^(\\d+:)?\\d+:\\d+$/) && t !== "LIVE" && t !== "สด" && t !== "Upcoming") {
                        if (t.length > bestTitle.length) {
                            bestTitle = t;
                            bestHref = a.href;
                        }
                    }
                }
                if (bestTitle && bestHref) {
                    results.push({
                        title: bestTitle,
                        href: bestHref
                    });
                }
            }
            return results;
        """)
        
        for item in extracted_data:
            title = item.get("title", "").strip()
            href = item.get("href", "").strip()
            if not title or not href:
                continue
                
            clean_url = clean_youtube_url(href)
            if not clean_url or "watch?v=" not in clean_url:
                continue
                
            parsed = urlparse(clean_url)
            qs = parse_qs(parsed.query)
            vid_id = qs.get("v", [""])[0] or clean_url
            
            if vid_id not in video_dict:
                video_dict[vid_id] = {
                    "title": title,
                    "url": clean_url,
                    "raw_title": title
                }
                
        videos = list(video_dict.values())
        print(f"\n[YouTube Crawler] ดึงรายการ Live Streams จาก YouTube ได้ทั้งหมด {len(videos)} รายการ:")
        for idx, v in enumerate(videos, start=1):
            print(f"  {idx}. {v['title']} -> {v['url']}")
            
        return videos
        
    finally:
        driver.quit()


def normalize_youtube_title(text: str) -> str:
    """
    ปรับรูปแบบข้อความชื่อรายการ YouTube ให้อยู่ในรูปมาตรฐานสำหรับจับคู่
    """
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"🔴|🟠|\[.*?\]|\(.*?\)", "", t)
    t = t.replace("็", "๊")
    t = re.sub(r"[\s\.\-:_’'\"!|#]", "", t)
    return t.lower()


def find_matching_youtube_video(
    videos: List[Dict[str, str]], 
    program_title: str, 
    broadcast_time: Optional[str] = None, 
    broadcast_date: Optional[str] = None,
    scheduled_dt: Optional[datetime] = None
) -> Optional[Dict[str, str]]:
    """
    ค้นหาวิดีโอ YouTube Live Streams ที่ตรงกับชื่อรายการ (Column C)
    กฎเกณฑ์การจับคู่:
    1. ตรวจสอบ 'วันที่' (อยู่หลังเครื่องหมาย '|' เช่น '| 7 ส.ค. 69') ต้องตรงกับ scheduled_dt
    2. ตรวจสอบชื่อรายการ (Title Matching): คำสำคัญหรือ Substring ของชื่อรายการต้องตรงกับส่วนใน Title
    """
    if not program_title or not videos:
        return None
        
    raw_title = program_title.strip()
    clean_search_title = normalize_youtube_title(raw_title)
    if not clean_search_title:
        return None

    # คำสำคัญที่ไม่ใช่ Stopwords
    all_words = [w for w in re.split(r"[\s\(\)\-_]+", raw_title) if w]
    sig_words = [w for w in all_words if len(w) > 1 and normalize_youtube_title(w) not in COMMON_STOPWORDS]
    if not sig_words:
        sig_words = all_words

    best_match = None
    highest_score = 0

    for video in videos:
        yt_title = video.get("title", "")
        
        # 1. ตรวจสอบวันที่ (Strict Date Verification)
        if scheduled_dt:
            target_day = scheduled_dt.day
            target_month = scheduled_dt.month
            target_ce_short = scheduled_dt.year % 100
            target_be_short = (scheduled_dt.year + 543) % 100
            
            yt_date = extract_thai_date_from_youtube_title(yt_title)
            if yt_date:
                day, month, year = yt_date
                # วันและเดือนต้องตรงกัน
                if day != target_day or month != target_month:
                    continue
                # หากมีปีระบุ ปีต้องตรงกันทั้งแบบ ค.ศ. หรือ พ.ศ.
                if year is not None:
                    valid_years = {target_ce_short, target_be_short, scheduled_dt.year, scheduled_dt.year + 543}
                    if year not in valid_years and (year % 100) not in valid_years:
                        continue
            else:
                continue

        # 2. ตรวจสอบชื่อรายการ (Title Matching)
        # แบ่งส่วนประกอบของ YouTube Title ตาม |
        parts = yt_title.split("|")
        norm_parts = [normalize_youtube_title(p) for p in parts]
        norm_full_title = normalize_youtube_title(yt_title)
        
        score = 0
        if clean_search_title in norm_parts or clean_search_title == norm_full_title:
            score += 100
        elif any(clean_search_title in np or np in clean_search_title for np in norm_parts if np):
            score += 85
        elif clean_search_title in norm_full_title:
            score += 80
        else:
            # ตรวจสอบการตรงกันของ Sig words
            matched_words = 0
            for w in sig_words:
                norm_w = normalize_youtube_title(w)
                if norm_w and (norm_w in norm_full_title or any(norm_w in np for np in norm_parts)):
                    matched_words += 1
            if matched_words == len(sig_words) and len(sig_words) > 0:
                score += 70
            elif matched_words > 0:
                score += 40 * (matched_words / len(sig_words))

        if score > highest_score and score >= 50:
            highest_score = score
            best_match = video

    return best_match
