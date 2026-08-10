from typing import Dict, List, Optional

import requests

# ค่าที่แสดงแทน "ไม่พบลิงก์" เมื่อเขียนลง Google Sheet / CSV (ตามที่ผู้ใช้กำหนด)
NOT_FOUND_DISPLAY = "-"


def fetch_schedule_rows(api_url: str, token: Optional[str] = None, timeout: int = 30) -> List[Dict]:
    """
    ดึงข้อมูลตารางเวลา (A: วันที่, B: เวลา, C: ชื่อรายการ) จาก Google Apps Script Web App
    (แทนที่การ export CSV ตรงๆ จาก Google Sheets ด้วย SHEET_ID/GID)
    คืนค่าเป็น List ของ { row, date, time, title }
    """
    params = {}
    if token:
        params["token"] = token

    response = requests.get(api_url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()

    if payload.get("status") != "ok":
        raise RuntimeError(f"Apps Script API ส่งค่า error กลับมา: {payload.get('message')}")

    return payload.get("data", [])


def write_row_result(
    api_url: str,
    row: int,
    date: str,
    time: str,
    title: str,
    facebook_url: str,
    youtube_url: str,
    x_url: str,
    token: Optional[str] = None,
    timeout: int = 30,
) -> bool:
    """
    เขียนผลลัพธ์ลิงก์ของแถวหนึ่งๆ กลับลง Google Sheet ผ่าน Apps Script Web App:
    - Facebook -> คอลัมน์ K
    - YouTube  -> คอลัมน์ M
    - X        -> คอลัมน์ N

    ส่ง date/time/title แนบไปพร้อมกับ row เสมอ เพื่อให้ฝั่ง Apps Script ตรวจสอบว่าแถวนั้น
    ตรงกับข้อมูลจริงในชีทก่อนเขียน (ป้องกันกรณีชื่อรายการซ้ำกันแต่คนละวัน เช่น
    "2026-08-09  06:00  ทันข่าว 06.00 น." กับรายการชื่อเดียวกันของวันอื่น หรือกรณีแถวเลื่อนตำแหน่ง)
    คืนค่า True หากเขียนสำเร็จ, False หากถูกข้ามหรือเกิดข้อผิดพลาด
    """
    fb_val = facebook_url if facebook_url and facebook_url != "NOT FOUND" else NOT_FOUND_DISPLAY
    yt_val = youtube_url if youtube_url and youtube_url != "NOT FOUND" else NOT_FOUND_DISPLAY
    x_val = x_url if x_url and x_url != "NOT FOUND" else NOT_FOUND_DISPLAY

    payload = {
        "row": row,
        "date": date,
        "time": time,
        "title": title,
        "facebook_url": fb_val,
        "youtube_url": yt_val,
        "x_url": x_val,
    }
    if token:
        payload["token"] = token

    try:
        response = requests.post(api_url, json=payload, timeout=timeout)
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "ok":
            print(f"[Sheet Writer] Apps Script ส่ง error กลับมา: {result.get('message')}")
            return False

        updated = result.get("updated", [])
        if updated and updated[0].get("status") == "skipped":
            print(f"[Sheet Writer] แถว {row} ('{title}') ถูกข้าม: {updated[0].get('reason')}")
            return False

        print(f"[Sheet Writer] เขียนผลลัพธ์แถว {row} ('{title}') ลง Google Sheet สำเร็จ ผ่าน Apps Script API")
        return True
    except Exception as e:
        print(f"[Warning] ไม่สามารถเขียนผลลัพธ์แถว {row} ('{title}') ผ่าน Apps Script API ได้: {e}")
        return False
