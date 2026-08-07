import csv
import io
import os
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests
from dotenv import load_dotenv

# นำเข้าฟังก์ชันจาก facebook.py และ youtube.py
from facebook import scrape_live_videos, find_matching_video
from youtube import scrape_youtube_streams, find_matching_youtube_video

load_dotenv(override=True)


def parse_schedule_datetime(date_str: str, time_str: str) -> Optional[datetime]:
    """
    แปลงวันที่ (A) และเวลา (B) จาก Google Sheet ให้เป็น datetime object
    รองรับหลายรูปแบบ เช่น:
    - Date: 2026-08-07, 07/08/2026, 7/8/2569 (พ.ศ.), 7 ส.ค. 69
    - Time: 05:00, 05.00, 10.30, 12.00-12.30 (ดึงเวลาเริ่มต้น)
    """
    try:
        date_clean = date_str.strip()
        time_clean = time_str.strip()
        
        # ปรับเวลา เช่น '05.00 น.', '12.00-12.30 น.'
        time_clean = time_clean.replace("น.", "").replace("น", "").strip()
        if "-" in time_clean:
            time_clean = time_clean.split("-")[0].strip()
        time_clean = time_clean.replace(".", ":")
        
        time_parts = time_clean.split(":")
        if len(time_parts) >= 2:
            hour = int(time_parts[0])
            minute = int(time_parts[1])
        else:
            return None

        # จัดการรูปแบบวันที่
        parsed_date = None
        date_clean = date_clean.replace("/", "-")
        date_parts = date_clean.split("-")
        
        if len(date_parts) == 3:
            p0, p1, p2 = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])
            if p0 > 2400:  # 2569-08-07
                year, month, day = p0 - 543, p1, p2
            elif p2 > 2400:  # 07-08-2569
                year, month, day = p2 - 543, p1, p0
            elif p0 > 1900:  # 2026-08-07
                year, month, day = p0, p1, p2
            else:  # 07-08-2026
                year, month, day = p2, p1, p0
            parsed_date = datetime(year, month, day, hour, minute)
            
        return parsed_date
    except Exception as e:
        print(f"[Warning] ไม่สามารถแปลงวันเวลา '{date_str} {time_str}': {e}")
        return None


def fetch_sheet_schedule(sheet_id: str, gid: str = "0", start_row: int = 6) -> List[Dict]:
    """
    ดึงข้อมูลตารางเวลาและรายการ (A: วันที่, B: เวลา, C: ชื่อรายการ)
    ตั้งแต่แถว start_row (ค่าเริ่มต้นคือแถว 6: A6:C) ผ่าน Google Sheets CSV Export API
    """
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    print(f"[Google Sheet] กำลังดึงข้อมูลจาก: {url}")
    
    response = requests.get(url)
    response.raise_for_status()
    
    # กำหนด encoding เป็น utf-8
    response.encoding = 'utf-8'
    csv_content = io.StringIO(response.text)
    reader = csv.reader(csv_content)
    
    schedule_list = []
    
    for row_idx, row in enumerate(reader, start=1):
        if row_idx < start_row:
            continue
            
        # ตรวจสอบว่าแถวนั้นมีข้อมูลอย่างน้อยในคอลัมน์ A, B, C หรือไม่
        if len(row) >= 3:
            date_val = row[0].strip()
            time_val = row[1].strip()
            title_val = row[2].strip()
            
            # ข้ามแถวที่ไม่มีชื่อรายการ (Column C)
            if not title_val:
                continue
                
            sched_dt = parse_schedule_datetime(date_val, time_val)
            
            schedule_list.append({
                "row": row_idx,
                "date": date_val,
                "time": time_val,
                "title": title_val,
                "datetime": sched_dt
            })
            
    print(f"[Google Sheet] ดึงข้อมูลแถว {start_row} ขึ้นไป สำเร็จ: ทั้งหมด {len(schedule_list)} รายการ\n")
    return schedule_list


def save_results_to_csv(results: List[Dict], filename: str = "live_results.csv") -> str:
    """
    บันทึกผลลัพธ์ลงไฟล์ CSV มี 4 คอลัมน์:
    - string ที่ค้นหา
    - วันเวลา
    - facebook url
    - youtube url
    """
    fieldnames = [
        "string ที่ค้นหา",
        "วันเวลา",
        "facebook url",
        "youtube url"
    ]
    
    filepath = os.path.join(os.getcwd(), filename)
    with open(filepath, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            datetime_str = f"{r.get('date', '')} {r.get('time', '')}".strip()
            writer.writerow({
                "string ที่ค้นหา": r.get("search_string", ""),
                "วันเวลา": datetime_str,
                "facebook url": r.get("facebook_url", "NOT FOUND"),
                "youtube url": r.get("youtube_url", "NOT FOUND")
            })
            
    print(f"\n[CSV] บันทึกผลลัพธ์ลงไฟล์ CSV เรียบร้อยแล้วที่: {filepath}")
    return filepath


def process_due_schedules(
    schedules: List[Dict], 
    facebook_url: str, 
    youtube_url: str,
    delay_minutes: int = 5,
    csv_filename: str = "live_results.csv"
) -> List[Dict]:
    """
    ตรวจสอบเงื่อนไขเวลา:
    เมื่อเวลาปัจจุบันของระบบ (System Time) เกินเวลาออกอากาศ (A, B) ไปแล้ว >= 5 นาที
    จะทำการ Crawl หน้า Facebook และ YouTube Live Streams เพื่อค้นหา Link รายการ
    พร้อมบันทึกผลลัพธ์ลงไฟล์ CSV
    """
    system_now = datetime.now()
    print(f"\n[System Time] เวลาปัจจุบันของระบบ: {system_now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    all_results = []
    due_items = []

    # 1. คัดกรองรายการที่ถึงเวลาค้นหา (เวลาปัจจุบัน >= เวลาออกอากาศ + 5 นาที)
    for item in schedules:
        sched_dt = item.get("datetime")
        if not sched_dt:
            due_items.append(item)
            continue
            
        trigger_time = sched_dt + timedelta(minutes=delay_minutes)
        if system_now >= trigger_time:
            due_items.append(item)
        else:
            wait_time = trigger_time - system_now
            print(f"[-] แถว {item['row']}: '{item['title']}' ({item['date']} {item['time']}) -> ยังไม่ถึงเวลาค้นหา (เหลืออีก {wait_time})")

    if not due_items:
        print("\n[Info] ยังไม่มีรายการที่เข้าเกณฑ์เกินเวลาออกอากาศ 5 นาทีในขณะนี้")
        return all_results

    print(f"\n[Info] พบ {len(due_items)} รายการที่เข้าเกณฑ์ (เกินเวลาออกอากาศ >= {delay_minutes} นาที)")
    
    # 2. Scrape วิดีโอจาก Facebook และ YouTube
    print("\n--- เริ่มต้น Scrape ข้อมูลจาก Facebook และ YouTube ---")
    fb_videos = scrape_live_videos(page_url=facebook_url, max_scrolls=25, load_wait_seconds=5)
    yt_videos = scrape_youtube_streams(channel_streams_url=youtube_url, max_scrolls=15, load_wait_seconds=5)
    
    # 3. นำแต่ละรายการ (C) ไปค้นหาและ match
    for item in due_items:
        title = item["title"]
        time_str = item["time"]
        date_str = item["date"]
        sched_dt = item.get("datetime")
        row_num = item["row"]
        
        print(f"\n[Search] กำลังค้นหารายการ: '{title}' (วันที่ {date_str}, เวลา {time_str})")
        
        # ค้นหาบน Facebook
        matched_fb = find_matching_video(
            videos=fb_videos, 
            program_title=title, 
            broadcast_time=time_str, 
            broadcast_date=date_str,
            scheduled_dt=sched_dt
        )
        fb_link = matched_fb["url"] if matched_fb else "NOT FOUND"
        if matched_fb:
            print(f"  [FB MATCHED] เจอ Facebook: {fb_link}")
        else:
            print(f"  [FB NOT FOUND] ไม่พบวิดีโอบน Facebook")

        # ค้นหาบน YouTube
        matched_yt = find_matching_youtube_video(
            videos=yt_videos,
            program_title=title,
            broadcast_time=time_str,
            broadcast_date=date_str,
            scheduled_dt=sched_dt
        )
        yt_link = matched_yt["url"] if matched_yt else "NOT FOUND"
        if matched_yt:
            print(f"  [YT MATCHED] เจอ YouTube: {yt_link}")
        else:
            print(f"  [YT NOT FOUND] ไม่พบวิดีโอบน YouTube")

        all_results.append({
            "row": row_num,
            "date": date_str,
            "time": time_str,
            "search_string": title,
            "facebook_url": fb_link,
            "youtube_url": yt_link,
            "status": "FOUND" if (fb_link != "NOT FOUND" or yt_link != "NOT FOUND") else "NOT FOUND"
        })

    # 4. บันทึกผลลัพธ์ลงไฟล์ CSV
    save_results_to_csv(all_results, filename=csv_filename)
    return all_results


def start_live_scheduler(
    sheet_id: str, 
    gid: str = "0", 
    facebook_url: str = "https://www.facebook.com/watch/ThaiPBS/", 
    youtube_url: str = "https://www.youtube.com/@ThaiPBS/streams",
    check_interval_seconds: int = 60,
    delay_minutes: int = 5,
    csv_filename: str = "live_results.csv"
):
    """
    Loop ตรวจสอบสถานะอัตโนมัติ เช็คตารางและ Crawl เมื่อถึงเวลาที่กำหนด
    """
    processed_rows = set()
    print(f"=== เริ่มต้นระบบติดตาม Live Scraper Automate ===")
    print(f"Facebook Target: {facebook_url}")
    print(f"YouTube Target:  {youtube_url}")
    print(f"Check Interval: ทุกๆ {check_interval_seconds} วินาที\n")

    while True:
        try:
            schedules = fetch_sheet_schedule(sheet_id=sheet_id, gid=gid, start_row=6)
            unprocessed_schedules = [s for s in schedules if s["row"] not in processed_rows]
            
            results = process_due_schedules(
                schedules=unprocessed_schedules,
                facebook_url=facebook_url,
                youtube_url=youtube_url,
                delay_minutes=delay_minutes,
                csv_filename=csv_filename
            )
            
            for res in results:
                if res.get("facebook_url") != "NOT FOUND" and res.get("youtube_url") != "NOT FOUND":
                    processed_rows.add(res["row"])
                
            print(f"\n[Scheduler] รอตรวจรอบถัดไปในอีก {check_interval_seconds} วินาที...\n")
            time.sleep(check_interval_seconds)
            
        except KeyboardInterrupt:
            print("\n[Scheduler] หยุดการทำงานโดยผู้ใช้")
            break
        except Exception as e:
            print(f"\n[Error] เกิดข้อผิดพลาดใน Scheduler: {e}")
            time.sleep(check_interval_seconds)


if __name__ == "__main__":
    SHEET_ID = os.getenv("SHEET_ID", "YOUR_SPREADSHEET_ID")
    GID = os.getenv("GID", "0")
    FACEBOOK_PAGE_URL = os.getenv("FACEBOOK_PAGE_URL", "https://www.facebook.com/watch/ThaiPBS/")
    YOUTUBE_STREAMS_URL = os.getenv("YOUTUBE_STREAMS_URL", "https://www.youtube.com/@ThaiPBS/streams")
    CSV_OUTPUT_FILE = os.getenv("CSV_OUTPUT_FILE", "live_results.csv")
    
    # 1. ดึงตารางจาก Google Sheet (A6:C)
    schedules = fetch_sheet_schedule(sheet_id=SHEET_ID, gid=GID, start_row=6)
    
    # 2. ตรวจสอบเงื่อนไขเวลาเกิน 5 นาที แล้ว Crawl หา Link ทั้ง Facebook & YouTube และบันทึก CSV
    results = process_due_schedules(
        schedules=schedules, 
        facebook_url=FACEBOOK_PAGE_URL, 
        youtube_url=YOUTUBE_STREAMS_URL,
        delay_minutes=5,
        csv_filename=CSV_OUTPUT_FILE
    )
    
    # 3. สรุปผลลัพธ์ลิงก์ที่ดึงมาได้
    print("\n" + "="*80)
    print("สรุปผลลัพธ์การค้นหา Live Streams (Facebook & YouTube):")
    print("="*80)
    for r in results:
        datetime_str = f"{r['date']} {r['time']}"
        print(f"แถว {r['row']} | {datetime_str} | {r['search_string']}")
        print(f"  - Facebook: {r['facebook_url']}")
        print(f"  - YouTube:  {r['youtube_url']}")
