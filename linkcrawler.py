import csv
import io
import os
import re
import sys
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import requests
from dotenv import load_dotenv

# รองรับการแสดงผลภาษาไทยบน Windows Terminal
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

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


def load_existing_results_from_csv(filename: str = "live_results.csv") -> Dict[str, Dict[str, str]]:
    """
    อ่านผลลัพธ์เดิมจากไฟล์ CSV (ถ้ามี) เพื่อไม่ต้องค้นหาซ้ำรายการที่เจอแล้ว
    คืนค่าเป็น Dictionary: { "วันที่_เวลา_ชื่อรายการ": { ... } }
    """
    existing = {}
    filepath = os.path.join(os.getcwd(), filename)
    if not os.path.exists(filepath):
        return existing
        
    try:
        with open(filepath, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                search_str = row.get("string ที่ค้นหา", "").strip()
                dt_str = row.get("วันเวลา", "").strip()
                fb_url = row.get("facebook url", "").strip()
                yt_url = row.get("youtube url", "").strip()
                if search_str:
                    key = f"{dt_str}_{search_str}"
                    parts = dt_str.split(" ", 1)
                    date_part = parts[0] if len(parts) > 0 else ""
                    time_part = parts[1] if len(parts) > 1 else ""
                    existing[key] = {
                        "date": date_part,
                        "time": time_part,
                        "search_string": search_str,
                        "title": search_str,
                        "facebook_url": fb_url or "NOT FOUND",
                        "youtube_url": yt_url or "NOT FOUND",
                        "attempts": 1 if (fb_url and fb_url != "NOT FOUND") or (yt_url and yt_url != "NOT FOUND") else 0
                    }
        print(f"[CSV] โหลดผลลัพธ์เดิมจาก {filename} สำเร็จ: พบ {len(existing)} รายการ")
    except Exception as e:
        print(f"[Warning] ไม่สามารถอ่านไฟล์ {filename} เดิมได้: {e}")
        
    return existing


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
    try:
        with open(filepath, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                date_val = str(r.get('date', '')).strip()
                time_val = str(r.get('time', '')).strip()
                datetime_str = r.get('datetime_str', '')
                if not datetime_str:
                    datetime_str = f"{date_val} {time_val}".strip()
                    
                search_val = r.get("search_string") or r.get("title") or ""
                writer.writerow({
                    "string ที่ค้นหา": search_val,
                    "วันเวลา": datetime_str,
                    "facebook url": r.get("facebook_url", "NOT FOUND"),
                    "youtube url": r.get("youtube_url", "NOT FOUND")
                })
        print(f"[CSV] อัปเดตและบันทึกผลลัพธ์ลงไฟล์ CSV เรียบร้อยแล้วที่: {filepath}")
    except PermissionError:
        print(f"[Warning] ไม่สามารถบันทึก {filename} ได้ เนื่องจากไฟล์ถูกเปิดใช้งานอยู่ (เช่น ใน Microsoft Excel)")
    except Exception as e:
        print(f"[Warning] เกิดข้อผิดพลาดในการบันทึก CSV: {e}")
        
    return filepath


def process_due_schedules(
    schedules: List[Dict], 
    facebook_url: str, 
    youtube_url: str,
    master_results: Dict[str, Dict],
    delay_minutes: int = 3,
    csv_filename: str = "live_results.csv",
    max_retry_minutes: int = 25
) -> Tuple[List[Dict], List[Dict]]:
    """
    ตรวจสอบเงื่อนไขเวลาในลักษณะ Sliding Queue:
    - แบ่งรายการตามเวลาออกอากาศ + Delay 3 นาที
    - รายการในอดีต (ถอยไป 1 รายการ): ตรวจสอบเฉพาะรายการล่าสุดที่ถึงเวลา (หน้า Queue ตัวเดียว) 
      หากยังไม่มีลิงก์ครบ จะทำการ Crawl หน้า Facebook และ YouTube Live Streams
    - รายการในอนาคต (ไปหน้า 1 รายการ): รอเวลาและแสดงเวลานับถอยหลัง
    
    คืนค่า (updated_items, upcoming_items)
    """
    system_now = datetime.now()
    
    # กรองเฉพาะรายการที่มี datetime ถูกต้อง และเรียงตามลำดับเวลา
    valid_schedules = [s for s in schedules if s.get("datetime")]
    valid_schedules.sort(key=lambda x: x["datetime"])
    
    past_items = []
    upcoming_items = []
    
    for item in valid_schedules:
        sched_dt = item["datetime"]
        trigger_time = sched_dt + timedelta(minutes=delay_minutes)
        item_copy = {**item, "trigger_time": trigger_time}
        
        if system_now >= trigger_time:
            past_items.append(item_copy)
        else:
            item_copy["wait_seconds"] = (trigger_time - system_now).total_seconds()
            upcoming_items.append(item_copy)
            
    due_items_to_search = []
    
    # 1. ถอยไป 1 รายการ: ดึงเฉพาะรายการล่าสุดที่ถึงเวลา (หน้า Queue ตัวเดียว)
    if past_items:
        latest_past_dt = past_items[-1]["datetime"]
        active_due_candidates = [it for it in past_items if it["datetime"] == latest_past_dt]
        
        for cand in active_due_candidates:
            key = f"{cand['date']} {cand['time']}_{cand['title']}"
            existing_res = master_results.get(key, {
                "facebook_url": "NOT FOUND",
                "youtube_url": "NOT FOUND",
                "attempts": 0
            })
            fb_url = existing_res.get("facebook_url", "NOT FOUND")
            yt_url = existing_res.get("youtube_url", "NOT FOUND")
            
            # หากยังไม่เจอครบทั้ง 2 ลิงก์ ให้ค้นหา
            if fb_url == "NOT FOUND" or yt_url == "NOT FOUND":
                due_items_to_search.append(cand)

    # แสดงสถานะคิวรอบเวลาปัจจุบัน (ถอยไป 1, ไปหน้า 1)
    print(f"\n" + "-"*70)
    if past_items:
        latest_item = past_items[-1]
        k = f"{latest_item['date']} {latest_item['time']}_{latest_item['title']}"
        res = master_results.get(k, {})
        fb = res.get("facebook_url", "NOT FOUND")
        yt = res.get("youtube_url", "NOT FOUND")
        status_str = "✅ มีลิงก์ครบแล้ว (FB & YT)" if (fb != "NOT FOUND" and yt != "NOT FOUND") else ("⚠️ มีลิงก์บางส่วน" if (fb != "NOT FOUND" or yt != "NOT FOUND") else "❌ ยังไม่พบลิงก์")
        print(f"📍 [Queue: ถอยไป 1 รายการ] แถว {latest_item['row']}: '{latest_item['title']}' ({latest_item['date']} {latest_item['time']}) -> {status_str}")
        if fb != "NOT FOUND":
            print(f"   • Facebook : {fb}")
        if yt != "NOT FOUND":
            print(f"   • YouTube  : {yt}")
    else:
        print("📍 [Queue: ถอยไป 1 รายการ] ไม่มีรายการในอดีต")

    if upcoming_items:
        next_item = upcoming_items[0]
        w_sec = int(next_item["wait_seconds"])
        w_min = w_sec // 60
        w_rem_sec = w_sec % 60
        print(f"⏳ [Queue: ไปหน้า 1 รายการ] แถว {next_item['row']}: '{next_item['title']}' ({next_item['date']} {next_item['time']}) -> เริ่มค้นหา {next_item['trigger_time'].strftime('%H:%M:%S')} (อีก {w_min:02d} นาที {w_rem_sec:02d} วินาที)")
    else:
        print("⏳ [Queue: ไปหน้า 1 รายการ] ไม่มีรายการถัดไปในผัง")
    print("-"*70)

    if not due_items_to_search:
        return [], upcoming_items

    print(f"\n" + "="*70)
    print(f"🔥 [Live Due] พบ {len(due_items_to_search)} รายการใน Queue ที่ถึงเวลาค้นหา (เวลาออกอากาศ + Delay {delay_minutes} นาที)")
    print(f"⏰ [System Time] {system_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    for it in due_items_to_search:
        print(f"  - แถว {it['row']}: '{it['title']}' (เวลา {it['date']} {it['time']})")

    # Scrape วิดีโอจาก Facebook และ YouTube
    print("\n--- เริ่มต้น Scrape ข้อมูลจาก Facebook และ YouTube ---")
    fb_videos = []
    yt_videos = []
    
    try:
        fb_videos = scrape_live_videos(page_url=facebook_url, max_scrolls=25, load_wait_seconds=5)
    except Exception as e:
        print(f"[Warning] เกิดข้อผิดพลาดขณะ Crawl Facebook: {e}")

    try:
        yt_videos = scrape_youtube_streams(channel_streams_url=youtube_url, max_scrolls=15, load_wait_seconds=5)
    except Exception as e:
        print(f"[Warning] เกิดข้อผิดพลาดขณะ Crawl YouTube: {e}")

    updated_items = []

    # นำแต่ละรายการไปค้นหาและ match
    for item in due_items_to_search:
        title = item["title"]
        time_str = item["time"]
        date_str = item["date"]
        sched_dt = item.get("datetime")
        row_num = item["row"]
        key = f"{date_str} {time_str}_{title}"
        
        curr_res = master_results.get(key, {
            "facebook_url": "NOT FOUND",
            "youtube_url": "NOT FOUND",
            "attempts": 0
        })
        fb_link = curr_res.get("facebook_url", "NOT FOUND")
        yt_link = curr_res.get("youtube_url", "NOT FOUND")
        attempts = curr_res.get("attempts", 0) + 1
        
        print(f"\n[Search] กำลังค้นหารายการ: '{title}' ({date_str} {time_str}) [ค้นหาครั้งที่ {attempts}]")
        
        # ค้นหาบน Facebook หากยังไม่เจอ
        if fb_link == "NOT FOUND" and fb_videos:
            matched_fb = find_matching_video(
                videos=fb_videos, 
                program_title=title, 
                broadcast_time=time_str, 
                broadcast_date=date_str,
                scheduled_dt=sched_dt
            )
            if matched_fb:
                fb_link = matched_fb["url"]
                print(f"  ✅ [FB MATCHED] เจอ Facebook: {fb_link}")
            else:
                print(f"  ❌ [FB NOT FOUND] ไม่พบวิดีโอบน Facebook ในรอบนี้")
        elif fb_link != "NOT FOUND":
            print(f"  ℹ️ [FB ALREADY FOUND] มีลิงก์ Facebook อยู่แล้ว: {fb_link}")

        # ค้นหาบน YouTube หากยังไม่เจอ
        if yt_link == "NOT FOUND" and yt_videos:
            matched_yt = find_matching_youtube_video(
                videos=yt_videos,
                program_title=title,
                broadcast_time=time_str,
                broadcast_date=date_str,
                scheduled_dt=sched_dt
            )
            if matched_yt:
                yt_link = matched_yt["url"]
                print(f"  ✅ [YT MATCHED] เจอ YouTube: {yt_link}")
            else:
                print(f"  ❌ [YT NOT FOUND] ไม่พบวิดีโอบน YouTube ในรอบนี้")
        elif yt_link != "NOT FOUND":
            print(f"  ℹ️ [YT ALREADY FOUND] มีลิงก์ YouTube อยู่แล้ว: {yt_link}")

        # อัปเดต master_results
        master_results[key] = {
            "row": row_num,
            "date": date_str,
            "time": time_str,
            "search_string": title,
            "title": title,
            "facebook_url": fb_link,
            "youtube_url": yt_link,
            "attempts": attempts,
            "last_checked": system_now.strftime('%Y-%m-%d %H:%M:%S')
        }
        updated_items.append(master_results[key])

    # บันทึกผลลัพธ์ทั้งหมดลง CSV (ดึงข้อมูลแถว ผัง และชื่อรายการจากตาราง Google Sheet เสมอ)
    all_rows_for_csv = []
    for s in schedules:
        k = f"{s['date']} {s['time']}_{s['title']}"
        res = master_results.get(k, {})
        all_rows_for_csv.append({
            "row": s["row"],
            "date": s["date"],
            "time": s["time"],
            "search_string": s["title"],
            "title": s["title"],
            "facebook_url": res.get("facebook_url", "NOT FOUND"),
            "youtube_url": res.get("youtube_url", "NOT FOUND")
        })
        
    save_results_to_csv(all_rows_for_csv, filename=csv_filename)
    return updated_items, upcoming_items


def start_live_scheduler(
    sheet_id: str, 
    gid: str = "0", 
    facebook_url: str = "https://www.facebook.com/watch/ThaiPBS/", 
    youtube_url: str = "https://www.youtube.com/@ThaiPBS/streams",
    check_interval_seconds: int = 30,
    delay_minutes: int = 3,
    csv_filename: str = "live_results.csv"
):
    """
    Loop ตรวจสอบสถานะอัตโนมัติ รันทิ้งไว้ต่อเนื่องจนกว่าผู้ใช้จะกด Ctrl + C
    - ตรวจสอบเวลา System Time เทียบกับตารางเวลาใน Google Sheets
    - เมื่อเวลาปัจจุบันเกินเวลาออกอากาศ + 3 นาที จะดึงรายการใหม่มา Crawl ค้นหา
    - อัปเดตผลลัพธ์ลง CSV อัตโนมัติแบบ Real-time
    """
    print("=" * 80)
    print("🚀 เริ่มต้นระบบ Live Scraper Automate (Continuous Scheduler Mode)")
    print("=" * 80)
    print(f"• Facebook Target : {facebook_url}")
    print(f"• YouTube Target  : {youtube_url}")
    print(f"• Check Interval  : ทุกๆ {check_interval_seconds} วินาที")
    print(f"• Stream Delay    : {delay_minutes} นาที (เผื่อเวลาให้ทีม Live ขึ้นสตรีมสด)")
    print(f"• CSV Output File : {csv_filename}")
    print("• กด Ctrl + C ได้ทุกเมื่อเพื่อหยุดการทำงานอย่างปลอดภัย\n")

    # โหลดผลลัพธ์เดิมจาก CSV
    loaded_results = load_existing_results_from_csv(csv_filename)
    master_results: Dict[str, Dict] = loaded_results.copy()

    iteration = 0
    schedules = []

    try:
        while True:
            iteration += 1
            system_now = datetime.now()
            print(f"\n{'='*30} รอบตรวจสอบที่ #{iteration} ({system_now.strftime('%Y-%m-%d %H:%M:%S')}) {'='*30}")

            # ดึงตารางจาก Google Sheet (ดึงใหม่ทุกรอบเพื่อรองรับการอัปเดตตาราง)
            try:
                schedules = fetch_sheet_schedule(sheet_id=sheet_id, gid=gid, start_row=6)
            except Exception as e:
                print(f"[Warning] ไม่สามารถดึงข้อมูลจาก Google Sheet ในรอบนี้: {e}")
                if not schedules:
                    print(f"[Scheduler] รอตรวจรอบถัดไปในอีก {check_interval_seconds} วินาที...")
                    time.sleep(check_interval_seconds)
                    continue

            # ประมวลผลรายการที่ถึงเวลา
            updated_items, upcoming_items = process_due_schedules(
                schedules=schedules,
                facebook_url=facebook_url,
                youtube_url=youtube_url,
                master_results=master_results,
                delay_minutes=delay_minutes,
                csv_filename=csv_filename
            )

            # สรุปสถานะภาพรวม
            total_items = len(schedules)
            completed_count = 0
            partial_count = 0
            not_found_count = 0

            for s in schedules:
                k = f"{s['date']} {s['time']}_{s['title']}"
                res = master_results.get(k, {})
                fb = res.get("facebook_url", "NOT FOUND")
                yt = res.get("youtube_url", "NOT FOUND")
                if fb != "NOT FOUND" and yt != "NOT FOUND":
                    completed_count += 1
                elif fb != "NOT FOUND" or yt != "NOT FOUND":
                    partial_count += 1
                else:
                    not_found_count += 1

            print(f"\n📊 [Status Summary] รายการทั้งหมด: {total_items} | เจอครบ (FB+YT): {completed_count} | เจอเพียง 1 ลิงก์: {partial_count} | ยังไม่พบ/รอเวลา: {not_found_count}")

            # แสดงข้อมูลรายการถัดไปที่กำลังรอเวลาออกอากาศ + delay
            if upcoming_items:
                # เรียงลำดับรายการตามเวลาที่ใกล้จะถึงที่สุด
                upcoming_items.sort(key=lambda x: x.get("trigger_time", datetime.max))
                next_item = upcoming_items[0]
                wait_sec = int(next_item["wait_seconds"])
                wait_min = wait_sec // 60
                wait_rem_sec = wait_sec % 60
                
                print(f"\n⏳ [Next Program] รายการถัดไปในตาราง:")
                print(f"   • ชื่อรายการ : '{next_item['title']}'")
                print(f"   • เวลาในผัง  : {next_item['date']} เวลา {next_item['time']} น.")
                print(f"   • เวลาเริ่มค้นหา (ผัง + {delay_minutes} นาที) : {next_item['trigger_time'].strftime('%H:%M:%S')} น.")
                print(f"   • นับถอยหลัง : อีก {wait_min:02d} นาที {wait_rem_sec:02d} วินาที (System Time: {system_now.strftime('%H:%M:%S')})")
            else:
                print("\n✅ [Info] ประมวลผลครบทุกรายการในผังปัจจุบันแล้ว (หรือไม่มีรายการที่รอเวลาข้างหน้า)")

            print(f"\n💤 [Scheduler] สแตนด์บายรอตรวจรอบถัดไปในอีก {check_interval_seconds} วินาที... (กด Ctrl+C เพื่อหยุด)")
            time.sleep(check_interval_seconds)

    except KeyboardInterrupt:
        print("\n\n" + "="*80)
        print("🛑 ได้รับคำสั่ง Ctrl + C: จบการทำงานของระบบเรียบร้อยแล้ว")
        print(f"💾 ไฟล์ผลลัพธ์บันทึกอยู่ที่: {os.path.abspath(csv_filename)}")
        print("="*80 + "\n")


if __name__ == "__main__":
    SHEET_ID = os.getenv("SHEET_ID", "1l_ITgFiz8SCCPAEoZMwr1Vw98PVduL6nNJRprPYCCXw")
    GID = os.getenv("GID", "0")
    FACEBOOK_PAGE_URL = os.getenv("FACEBOOK_PAGE_URL", "https://www.facebook.com/watch/ThaiPBS/")
    YOUTUBE_STREAMS_URL = os.getenv("YOUTUBE_STREAMS_URL", "https://www.youtube.com/@ThaiPBS/streams")
    CSV_OUTPUT_FILE = os.getenv("CSV_OUTPUT_FILE", "live_results.csv")
    CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "30"))
    DELAY_MINUTES = int(os.getenv("DELAY_MINUTES", "3"))
    
    # รันระบบ Scheduler แบบต่อเนื่องจนกว่าจะกด Ctrl + C
    start_live_scheduler(
        sheet_id=SHEET_ID,
        gid=GID,
        facebook_url=FACEBOOK_PAGE_URL,
        youtube_url=YOUTUBE_STREAMS_URL,
        check_interval_seconds=CHECK_INTERVAL_SECONDS,
        delay_minutes=DELAY_MINUTES,
        csv_filename=CSV_OUTPUT_FILE
    )
