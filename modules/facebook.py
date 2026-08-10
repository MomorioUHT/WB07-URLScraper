import os
import re
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from modules.utilities import (
    THAI_MONTH_REGEX,
    create_stealth_chrome_driver,
    gregorian_year_to_be_short,
    normalize_title_text,
    parse_thai_date_match,
)

COMMON_STOPWORDS = {"ไทยพีบีเอส", "thaipbs", "live", "สด", "น", "recap", "hd", "ช่อง", "หมายเลข3"}


def create_driver(headless: bool = True) -> webdriver.Chrome:
    """
    สร้างและตั้งค่า Selenium Chrome WebDriver พร้อม Stealth Arguments (สำหรับ Facebook)
    """
    return create_stealth_chrome_driver(headless=headless)


def dismiss_login_popup(driver: webdriver.Chrome, debug_screenshot_path: Optional[str] = None):
    """
    ปิด Popup Login Modal และ Dialog บังหน้าจอ
    หากระบุ debug_screenshot_path จะถ่ายภาพหน้าจอหลังพยายามปิด popup ไว้ให้ตรวจสอบว่า
    ปิดสำเร็จจริงหรือไม่ (สำหรับ debug กรณีที่ crawler ดึงวิดีโอไม่เจอ)
    """
    try:
        # หมายเหตุ: บาง popup login ของ Facebook ไม่ได้อยู่ใน div[role='dialog']
        # (เช่น floating close button เดี่ยวๆ ที่มี aria-label='ปิด'/'Close' และ role='button')
        # จึงต้องค้นหา close button โดยตรงเสมอ ไม่ผูกเงื่อนไขไว้กับการเจอ div[role='dialog'] ก่อน
        xpaths = [
            "//div[@role='button' and @aria-label='ปิด']",
            "//div[@role='button' and @aria-label='Close']",
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

    if debug_screenshot_path:
        try:
            driver.save_screenshot(debug_screenshot_path)
            print(f"[Facebook Crawler] บันทึกภาพหน้าจอ Debug หลังปิด Popup ไว้ที่: {debug_screenshot_path}")
        except Exception as e:
            print(f"[Warning] ไม่สามารถบันทึกภาพหน้าจอ Debug ได้: {e}")


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
    pattern = rf"\(?\s*(\d{{1,2}})\s*({THAI_MONTH_REGEX})(?:\s*(\d{{2,4}}))?\s*\)?"
    match = re.search(pattern, title)
    return parse_thai_date_match(match)


def scrape_live_videos(page_url: str = "https://www.facebook.com/watch/ThaiPBS/", max_scrolls: int = 20, load_wait_seconds: int = 5, debug: bool = False) -> List[Dict[str, str]]:
    """
    Crawl ข้อมูลวิดีโอจากหน้า Facebook Watch Grid
    หาก debug=True จะถ่ายภาพหน้าจอหลังพยายามปิด popup login ครั้งแรกไว้ที่
    debug_facebook_after_close.png เพื่อตรวจสอบว่าปิด popup สำเร็จจริงหรือไม่
    """
    driver = create_driver(headless=True)
    video_dict: Dict[str, Dict[str, object]] = {}

    try:
        print(f"[Facebook Crawler] กำลังเปิดหน้าเว็บ: {page_url}")
        driver.get(page_url)

        # 1. รอให้หน้าเว็บโหลด
        print(f"[Facebook Crawler] รอให้หน้าเว็บโหลดเนื้อหา ({load_wait_seconds} วินาที)...")
        time.sleep(load_wait_seconds)
        debug_shot_path = os.path.join(os.getcwd(), "debug_facebook_after_close.png") if debug else None
        dismiss_login_popup(driver, debug_screenshot_path=debug_shot_path)

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

                // ตรวจสอบ badge "LIVE" (ป้ายกำลังถ่ายทอดสด) ที่ overlay อยู่บน thumbnail ของวิดีโอ
                // ใช้เป็น fallback เมื่อ Thai date ใน title ตรวจสอบไม่ผ่าน/ไม่พบ
                let isLive = Array.from(a.querySelectorAll('span')).some(
                    s => (s.textContent || '').trim() === 'LIVE'
                );

                results.push({
                    href: href,
                    text: cardText,
                    live: isLive
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
                is_live = bool(item.get("live", False))

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
                    # การ์ดเดียวกันอาจมีหลาย <a> (thumbnail กับ title) รวม LIVE badge ไว้ด้วย OR
                    video_dict[canonical_key]["is_live"] = video_dict[canonical_key].get("is_live", False) or is_live
                else:
                    video_dict[canonical_key] = {
                        "title": raw_text,
                        "url": clean_url,
                        "raw_text": raw_text,
                        "is_live": is_live
                    }
            except Exception:
                continue

        videos = list(video_dict.values())
        return videos
        
    finally:
        driver.quit()


def _score_title_match(card_text: str, clean_search_title: str, sig_words: List[str]) -> Tuple[bool, int]:
    """
    ตรวจสอบว่าชื่อรายการ/keyword ปรากฏอยู่ใน card_text หรือไม่ พร้อมให้คะแนนความมั่นใจ
    ใช้ร่วมกันทั้งการจับคู่แบบปกติ (เช็ควันที่) และแบบ fallback (เช็ค LIVE badge)
    """
    norm_card_text = normalize_title_text(card_text)

    if clean_search_title in norm_card_text:
        return True, 30

    matched_sig = [w for w in sig_words if normalize_title_text(w) in norm_card_text]
    if len(sig_words) == 1 and matched_sig:
        return True, 25
    if len(sig_words) > 1 and len(matched_sig) >= len(sig_words):
        return True, 25
    if len(sig_words) > 1 and len(matched_sig) >= max(1, len(sig_words) - 1):
        return True, 15

    return False, 0


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

        # 1. ตรวจสอบวันที่ (Strict Date Verification)
        if scheduled_dt:
            sched_day = scheduled_dt.day
            sched_month = scheduled_dt.month
            sched_year_be = gregorian_year_to_be_short(scheduled_dt.year)  # เช่น 2569 -> 69

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
        title_matched, title_score = _score_title_match(card_text, clean_search_title, sig_words)

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

    if best_match is not None:
        return best_match

    # 4. Fallback: หาก Thai date ใน title ตรวจสอบไม่ผ่าน/ไม่พบเลย (best_match ยังเป็น None)
    # ให้ใช้ badge "LIVE" (กำลังถ่ายทอดสดอยู่จริง ณ ขณะนี้) แทนการเช็ควันที่
    # โดยยังต้องจับคู่ชื่อรายการ/keyword กับ title ให้ผ่านเหมือนเดิม ก่อนจะยืนยันว่าไม่พบจริงๆ
    if scheduled_dt is not None:
        fallback_match = None
        fallback_score = 0
        for video in videos:
            if not video.get("is_live", False):
                continue

            card_text = video.get("title", "")
            title_matched, title_score = _score_title_match(card_text, clean_search_title, sig_words)
            if not title_matched:
                continue

            score = title_score
            if time_regex and time_regex.search(card_text):
                score += 10

            if score > fallback_score:
                fallback_score = score
                fallback_match = video

        if fallback_match is not None:
            print(
                "[Facebook Crawler] ตรวจสอบวันที่ไทยใน title ไม่พบ/ไม่ตรง "
                "แต่พบวิดีโอที่กำลัง LIVE และชื่อรายการตรงกัน จึงใช้ผลลัพธ์นี้แทน"
            )
            return fallback_match

    return None
