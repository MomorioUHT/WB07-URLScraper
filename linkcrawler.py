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

# นำเข้าฟังก์ชันจาก modules/facebook.py, modules/youtube.py และ modules/x.py
from modules.facebook import scrape_live_videos, find_matching_video
from modules.youtube import scrape_youtube_streams, find_matching_youtube_video
from modules.x import scrape_x_live_videos, find_matching_x_video

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


def fetch_sheet_schedule(sheet_id: str, gid: str, start_row: int = 6) -> List[Dict]:
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


def load_existing_results_from_csv(filename: str) -> Dict[str, Dict[str, str]]:
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
                x_url = row.get("x url", "").strip()
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
                        "x_url": x_url or "NOT FOUND",
                        "fb_attempts": 0,
                        "yt_attempts": 0,
                        "x_attempts": 0
                    }
        print(f"[CSV] โหลดผลลัพธ์เดิมจาก {filename} สำเร็จ: พบ {len(existing)} รายการ")
    except Exception as e:
        print(f"[Warning] ไม่สามารถอ่านไฟล์ {filename} เดิมได้: {e}")

    return existing


def save_results_to_csv(results: List[Dict], filename: str) -> str:
    """
    บันทึกผลลัพธ์ลงไฟล์ CSV มี 5 คอลัมน์:
    - string ที่ค้นหา
    - วันเวลา
    - facebook url
    - youtube url
    - x url
    """
    fieldnames = [
        "string ที่ค้นหา",
        "วันเวลา",
        "facebook url",
        "youtube url",
        "x url"
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
                    "youtube url": r.get("youtube_url", "NOT FOUND"),
                    "x url": r.get("x_url", "NOT FOUND")
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
    x_url: str,
    page_wait_seconds_fb: int,
    page_wait_seconds_yt: int,
    page_wait_seconds_x: int,
    master_results: Dict[str, Dict],
    delay_minutes: int,
    csv_filename: str
) -> Tuple[List[Dict], List[Dict]]:
    """
    ตรวจสอบเงื่อนไขเวลาในลักษณะ Sliding Queue:
    - แบ่งรายการตามเวลาออกอากาศ + Delay 4 นาที
    - รายการในอดีต (ถอยไป 1 รายการ): ตรวจสอบเฉพาะรายการล่าสุดที่ถึงเวลา (หน้า Queue ตัวเดียว)
      แต่ละ platform (Facebook / YouTube / X) มีสถานะ "จบ" ของตัวเองอย่างเป็นอิสระต่อกัน:
      1. หาก platform นั้นเจอ url แล้ว -> ถือว่าจบ ไม่ค้นหาซ้ำอีก
      2. หาก platform นั้นค้นหาครบ MAX_ATTEMPTS_PER_PLATFORM ครั้งแล้วไม่พบ -> ถือว่าจบ (ยอมแพ้) ไม่ค้นหาซ้ำอีก
      3. รายการจะถูก Skip ไปรายการถัดไป ก็ต่อเมื่อทุก platform "จบ" ครบทั้งหมดแล้วเท่านั้น
         หากยังมี platform ใดที่ยังไม่จบ จะทำการ Crawl ค้นหาต่อเฉพาะ platform ที่ยังไม่จบ
    - รายการในอนาคต (ไปหน้า 1 รายการ): รอเวลาและแสดงเวลานับถอยหลัง

    คืนค่า (updated_items, upcoming_items)
    """
    MAX_ATTEMPTS_PER_PLATFORM = 2
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
                "x_url": "NOT FOUND",
                "fb_attempts": 0,
                "yt_attempts": 0,
                "x_attempts": 0
            })
            fb_url = existing_res.get("facebook_url", "NOT FOUND")
            yt_url = existing_res.get("youtube_url", "NOT FOUND")
            x_link_existing = existing_res.get("x_url", "NOT FOUND")
            fb_attempts = existing_res.get("fb_attempts", 0)
            yt_attempts = existing_res.get("yt_attempts", 0)
            x_attempts = existing_res.get("x_attempts", 0)

            fb_done = (fb_url != "NOT FOUND") or (fb_attempts >= MAX_ATTEMPTS_PER_PLATFORM)
            yt_done = (yt_url != "NOT FOUND") or (yt_attempts >= MAX_ATTEMPTS_PER_PLATFORM)
            x_done = (x_link_existing != "NOT FOUND") or (x_attempts >= MAX_ATTEMPTS_PER_PLATFORM)

            # Skip ไปรายการถัดไป ก็ต่อเมื่อทุก platform จบแล้ว (เจอ หรือ ค้นหาครบจำนวนครั้งแล้ว)
            if fb_done and yt_done and x_done:
                continue

            # ยังมี platform ที่ยังไม่จบ -> ค้นหาต่อ (เฉพาะ platform ที่ยังไม่จบ)
            due_items_to_search.append(cand)

    # แสดงสถานะคิวรอบเวลาปัจจุบัน (ถอยไป 1, ไปหน้า 1)
    print(f"\n" + "-"*70)
    if past_items:
        latest_item = past_items[-1]
        k = f"{latest_item['date']} {latest_item['time']}_{latest_item['title']}"
        res = master_results.get(k, {})
        fb = res.get("facebook_url", "NOT FOUND")
        yt = res.get("youtube_url", "NOT FOUND")
        x_link = res.get("x_url", "NOT FOUND")
        fb_attempts = res.get("fb_attempts", 0)
        yt_attempts = res.get("yt_attempts", 0)
        x_attempts = res.get("x_attempts", 0)

        has_fb = (fb and fb != "NOT FOUND")
        has_yt = (yt and yt != "NOT FOUND")
        has_x = (x_link and x_link != "NOT FOUND")

        fb_done = has_fb or fb_attempts >= MAX_ATTEMPTS_PER_PLATFORM
        yt_done = has_yt or yt_attempts >= MAX_ATTEMPTS_PER_PLATFORM
        x_done = has_x or x_attempts >= MAX_ATTEMPTS_PER_PLATFORM

        if has_fb and has_yt and has_x:
            status_str = "✅ มีลิงก์ครบแล้ว (FB, YT & X) -> ข้ามไปรายการถัดไป"
        elif fb_done and yt_done and x_done:
            status_str = "❌ ค้นหาครบจำนวนครั้งที่กำหนดแล้ว (บางแพลตฟอร์มไม่พบ) -> ข้ามไปรายการถัดไป"
        else:
            status_str = "🔄 กำลังค้นหา / รอค้นหาต่อ (บาง platform ยังไม่จบ)"

        print(f"📍 [Queue: ถอยไป 1 รายการ] แถว {latest_item['row']}: '{latest_item['title']}' ({latest_item['date']} {latest_item['time']}) -> {status_str}")

        def _platform_line(name: str, found: bool, url: str, attempts_used: int, done: bool) -> str:
            if found:
                return f"   • {name} : {url}"
            elif done:
                return f"   • {name} : NOT FOUND (ค้นหาครบ {attempts_used}/{MAX_ATTEMPTS_PER_PLATFORM} ครั้งแล้ว ยอมแพ้)"
            else:
                return f"   • {name} : ยังไม่พบ (ค้นหาไปแล้ว {attempts_used}/{MAX_ATTEMPTS_PER_PLATFORM} ครั้ง)"

        print(_platform_line("Facebook", has_fb, fb, fb_attempts, fb_done))
        print(_platform_line("YouTube ", has_yt, yt, yt_attempts, yt_done))
        print(_platform_line("X       ", has_x, x_link, x_attempts, x_done))
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

    # Scrape วิดีโอจาก Facebook, YouTube และ X
    print("\n--- เริ่มต้น Scrape ข้อมูลจาก Facebook, YouTube และ X ---")
    fb_videos = []
    yt_videos = []
    x_videos = []

    try:
        fb_videos = scrape_live_videos(page_url=facebook_url, max_scrolls=25, load_wait_seconds=page_wait_seconds_fb)
    except Exception as e:
        print(f"[Warning] เกิดข้อผิดพลาดขณะ Crawl Facebook: {e}")

    try:
        yt_videos = scrape_youtube_streams(channel_streams_url=youtube_url, max_scrolls=15, load_wait_seconds=page_wait_seconds_yt)
    except Exception as e:
        print(f"[Warning] เกิดข้อผิดพลาดขณะ Crawl YouTube: {e}")

    try:
        x_videos = scrape_x_live_videos(page_url=x_url, max_scrolls=3, load_wait_seconds=page_wait_seconds_x)
    except Exception as e:
        print(f"[Warning] เกิดข้อผิดพลาดขณะ Crawl X: {e}")

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
            "x_url": "NOT FOUND",
            "fb_attempts": 0,
            "yt_attempts": 0,
            "x_attempts": 0
        })
        fb_link = curr_res.get("facebook_url", "NOT FOUND")
        yt_link = curr_res.get("youtube_url", "NOT FOUND")
        x_link = curr_res.get("x_url", "NOT FOUND")
        fb_attempts = curr_res.get("fb_attempts", 0)
        yt_attempts = curr_res.get("yt_attempts", 0)
        x_attempts = curr_res.get("x_attempts", 0)

        print(f"\n[Search] กำลังค้นหารายการ: '{title}' ({date_str} {time_str})")

        # ค้นหาบน Facebook หากยังไม่เจอ และยังไม่ครบจำนวนครั้งที่ลองได้
        if fb_link == "NOT FOUND" and fb_attempts < MAX_ATTEMPTS_PER_PLATFORM:
            fb_attempts += 1
            matched_fb = find_matching_video(
                videos=fb_videos,
                program_title=title,
                broadcast_time=time_str,
                broadcast_date=date_str,
                scheduled_dt=sched_dt
            )
            if matched_fb:
                fb_link = matched_fb["url"]
                print(f"  ✅ [FB MATCHED] เจอ Facebook (ครั้งที่ {fb_attempts}): {fb_link}")
            else:
                print(f"  ❌ [FB NOT FOUND] ไม่พบวิดีโอบน Facebook (ครั้งที่ {fb_attempts}/{MAX_ATTEMPTS_PER_PLATFORM})")
        elif fb_link != "NOT FOUND":
            print(f"  ℹ️ [FB ALREADY FOUND] มีลิงก์ Facebook อยู่แล้ว: {fb_link}")
        else:
            print(f"  🚫 [FB GIVE UP] ค้นหาครบ {fb_attempts} ครั้งแล้ว ไม่พบ Facebook สำหรับรายการนี้")

        # ค้นหาบน YouTube หากยังไม่เจอ และยังไม่ครบจำนวนครั้งที่ลองได้
        if yt_link == "NOT FOUND" and yt_attempts < MAX_ATTEMPTS_PER_PLATFORM:
            yt_attempts += 1
            matched_yt = find_matching_youtube_video(
                videos=yt_videos,
                program_title=title,
                broadcast_time=time_str,
                broadcast_date=date_str,
                scheduled_dt=sched_dt
            )
            if matched_yt:
                yt_link = matched_yt["url"]
                print(f"  ✅ [YT MATCHED] เจอ YouTube (ครั้งที่ {yt_attempts}): {yt_link}")
            else:
                print(f"  ❌ [YT NOT FOUND] ไม่พบวิดีโอบน YouTube (ครั้งที่ {yt_attempts}/{MAX_ATTEMPTS_PER_PLATFORM})")
        elif yt_link != "NOT FOUND":
            print(f"  ℹ️ [YT ALREADY FOUND] มีลิงก์ YouTube อยู่แล้ว: {yt_link}")
        else:
            print(f"  🚫 [YT GIVE UP] ค้นหาครบ {yt_attempts} ครั้งแล้ว ไม่พบ YouTube สำหรับรายการนี้")

        # ค้นหาบน X หากยังไม่เจอ และยังไม่ครบจำนวนครั้งที่ลองได้
        if x_link == "NOT FOUND" and x_attempts < MAX_ATTEMPTS_PER_PLATFORM:
            x_attempts += 1
            matched_x = find_matching_x_video(
                videos=x_videos,
                program_title=title,
                broadcast_time=time_str,
                broadcast_date=date_str,
                scheduled_dt=sched_dt
            )
            if matched_x:
                x_link = matched_x["url"]
                print(f"  ✅ [X MATCHED] เจอ X (ครั้งที่ {x_attempts}): {x_link}")
            else:
                print(f"  ❌ [X NOT FOUND] ไม่พบวิดีโอบน X (ครั้งที่ {x_attempts}/{MAX_ATTEMPTS_PER_PLATFORM})")
        elif x_link != "NOT FOUND":
            print(f"  ℹ️ [X ALREADY FOUND] มีลิงก์ X อยู่แล้ว: {x_link}")
        else:
            print(f"  🚫 [X GIVE UP] ค้นหาครบ {x_attempts} ครั้งแล้ว ไม่พบ X สำหรับรายการนี้")

        # อัปเดต master_results
        master_results[key] = {
            "row": row_num,
            "date": date_str,
            "time": time_str,
            "search_string": title,
            "title": title,
            "facebook_url": fb_link,
            "youtube_url": yt_link,
            "x_url": x_link,
            "fb_attempts": fb_attempts,
            "yt_attempts": yt_attempts,
            "x_attempts": x_attempts,
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
            "youtube_url": res.get("youtube_url", "NOT FOUND"),
            "x_url": res.get("x_url", "NOT FOUND")
        })

    save_results_to_csv(all_rows_for_csv, filename=csv_filename)
    return updated_items, upcoming_items


def start_live_scheduler(
    sheet_id: str,
    gid: str,
    facebook_url: str,
    youtube_url: str,
    x_url: str,
    page_wait_seconds_fb: int,
    page_wait_seconds_yt: int,
    page_wait_seconds_x: int,
    check_interval_seconds: int,
    delay_minutes: int,
    csv_filename: str
):
    """
    Loop ตรวจสอบสถานะอัตโนมัติ รันทิ้งไว้ต่อเนื่องจนกว่าผู้ใช้จะกด Ctrl + C
    - ดึงตารางเวลาจาก Google Sheets เพียงครั้งเดียวตอนเริ่มโปรแกรม (ไม่ดึงซ้ำทุกรอบ)
    - ตรวจสอบเวลา System Time เทียบกับตารางเวลาที่โหลดไว้
    - เมื่อเวลาปัจจุบันเกินเวลาออกอากาศ + 4 นาที จะดึงรายการใหม่มา Crawl ค้นหา
    - อัปเดตผลลัพธ์ลง CSV อัตโนมัติแบบ Real-time
    """
    print("=" * 80)
    print("🚀 เริ่มต้นระบบ Live Scraper Automate (Continuous Scheduler Mode)")
    print("=" * 80)
    print(f"• Facebook Target : {facebook_url}")
    print(f"• YouTube Target  : {youtube_url}")
    print(f"• X Target        : {x_url}")
    print(f"• Check Interval  : ทุกๆ {check_interval_seconds} วินาที")
    print(f"• Stream Delay    : {delay_minutes} นาที (เผื่อเวลาให้ทีม Live ขึ้นสตรีมสด)")
    print(f"• CSV Output File : {csv_filename}")
    print("• กด Ctrl + C ได้ทุกเมื่อเพื่อหยุดการทำงานอย่างปลอดภัย\n")

    # โหลดผลลัพธ์เดิมจาก CSV
    loaded_results = load_existing_results_from_csv(csv_filename)
    master_results: Dict[str, Dict] = loaded_results.copy()

    # ดึงตารางจาก Google Sheet เพียงครั้งเดียวตอนเปิดโปรแกรม
    try:
        schedules: List[Dict] = fetch_sheet_schedule(sheet_id=sheet_id, gid=gid, start_row=6)
    except Exception as e:
        print(f"[Error] ไม่สามารถดึงข้อมูลจาก Google Sheet ได้: {e}")
        return

    iteration = 0

    try:
        while True:
            iteration += 1
            system_now = datetime.now()
            print(f"\n{'='*30} รอบตรวจสอบที่ #{iteration} ({system_now.strftime('%Y-%m-%d %H:%M:%S')}) {'='*30}")

            # ประมวลผลรายการที่ถึงเวลา
            updated_items, upcoming_items = process_due_schedules(
                schedules=schedules,
                facebook_url=facebook_url,
                youtube_url=youtube_url,
                x_url=x_url,
                page_wait_seconds_fb=page_wait_seconds_fb,
                page_wait_seconds_yt=page_wait_seconds_yt,
                page_wait_seconds_x=page_wait_seconds_x,
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
                x_link = res.get("x_url", "NOT FOUND")
                if fb != "NOT FOUND" and yt != "NOT FOUND" and x_link != "NOT FOUND":
                    completed_count += 1
                elif fb != "NOT FOUND" or yt != "NOT FOUND" or x_link != "NOT FOUND":
                    partial_count += 1
                else:
                    not_found_count += 1

            print(f"\n📊 [Status Summary] รายการทั้งหมด: {total_items} | เจอครบ (FB+YT+X): {completed_count} | เจอบางส่วน: {partial_count} | ยังไม่พบ/รอเวลา: {not_found_count}")

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


def require_env(key: str) -> str:
    """
    อ่านค่า config จาก .env แบบบังคับ (ห้าม hardcode ค่าใดๆ ไว้ในโค้ด)
    หากไม่พบค่าใน .env จะหยุดโปรแกรมพร้อมแจ้งเตือนทันที
    """
    val = os.getenv(key)
    if not val:
        raise SystemExit(f"[Config Error] ไม่พบค่า '{key}' ในไฟล์ .env กรุณาตรวจสอบไฟล์ .env ก่อนรันโปรแกรม")
    return val


if __name__ == "__main__":
    SHEET_ID = require_env("SHEET_ID")
    GID = require_env("GID")
    CSV_OUTPUT_FILE = require_env("CSV_OUTPUT_FILE")
    CHECK_INTERVAL_SECONDS = int(require_env("CHECK_INTERVAL_SECONDS"))
    DELAY_MINUTES = int(require_env("DELAY_MINUTES"))

    PAGE_URL_FB = require_env("PAGE_URL_FB")
    PAGE_WAIT_SECONDS_FB = int(require_env("PAGE_WAIT_SECONDS_FB"))

    PAGE_URL_YT = require_env("PAGE_URL_YT")
    PAGE_WAIT_SECONDS_YT = int(require_env("PAGE_WAIT_SECONDS_YT"))

    PAGE_URL_X = require_env("PAGE_URL_X")
    PAGE_WAIT_SECONDS_X = int(require_env("PAGE_WAIT_SECONDS_X"))

    # รันระบบ Scheduler แบบต่อเนื่องจนกว่าจะกด Ctrl + C
    start_live_scheduler(
        sheet_id=SHEET_ID,
        gid=GID,
        facebook_url=PAGE_URL_FB,
        youtube_url=PAGE_URL_YT,
        x_url=PAGE_URL_X,
        page_wait_seconds_fb=PAGE_WAIT_SECONDS_FB,
        page_wait_seconds_yt=PAGE_WAIT_SECONDS_YT,
        page_wait_seconds_x=PAGE_WAIT_SECONDS_X,
        check_interval_seconds=CHECK_INTERVAL_SECONDS,
        delay_minutes=DELAY_MINUTES,
        csv_filename=CSV_OUTPUT_FILE
    )
