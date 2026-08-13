"""
login_facebook.py
------------------
เปิด Chrome แบบเห็นหน้าจอ (ไม่ headless) โดยใช้ Chrome Profile ที่ chrome_data/facebook_profile
ให้ผู้ใช้ Login เข้าบัญชี Facebook ด้วยตนเอง เมื่อ Login สำเร็จแล้ว Chrome จะบันทึก Session/Cookies
ลงในโปรไฟล์นี้อัตโนมัติ ทำให้ linkcrawler.py (ผ่าน modules/facebook.py, youtube.py, x.py ที่ใช้
create_stealth_chrome_driver() ร่วมกัน) เห็น Live Video ที่ต้อง Login บัญชี Facebook ก่อนถึงจะดูได้

วิธีใช้: python login_facebook.py
เมื่อต้องการ Logout และล้าง Session ทิ้ง ให้รัน logout_facebook.py
"""
from modules.utilities import FACEBOOK_PROFILE_DIR, create_stealth_chrome_driver


def main():
    print("=" * 70)
    print(f"[Login Facebook] กำลังเปิด Chrome โดยใช้ Profile ที่: {FACEBOOK_PROFILE_DIR}")
    driver = create_stealth_chrome_driver(headless=False)

    try:
        driver.get("https://www.facebook.com/login")
        print("[Login Facebook] กรุณา Login เข้าบัญชี Facebook ในหน้าต่าง Chrome ที่เปิดขึ้นมา")
        input("[Login Facebook] เมื่อ Login สำเร็จแล้ว (เห็นหน้า Feed/Home) ให้กลับมากด Enter ที่นี่...\n")

        cookies = driver.get_cookies()
        logged_in = any(c.get("name") == "c_user" for c in cookies)
        if logged_in:
            print("[Login Facebook] ✅ ตรวจพบ Session ที่ Login สำเร็จแล้ว")
        else:
            print("[Login Facebook] ⚠️ ยังไม่พบ Session ที่ Login (อาจ Login ไม่สำเร็จ) กรุณาลองรันใหม่อีกครั้ง")
    finally:
        driver.quit()
        print(f"[Login Facebook] ปิด Chrome แล้ว Session ถูกบันทึกไว้ที่: {FACEBOOK_PROFILE_DIR}")
        print("=" * 70)


if __name__ == "__main__":
    main()
