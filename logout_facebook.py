"""
logout_facebook.py
-------------------
Logout บัญชี Facebook ออกจาก Chrome Profile ที่ login_facebook.py สร้างไว้ (Best Effort ผ่านการ
กดปุ่ม Logout บนหน้าเว็บ) จากนั้นลบไดเรกทอรี chrome_data/facebook_profile ทิ้งทั้งหมด เพื่อล้าง
Cookies/Session ให้สะอาดจริงๆ (ต้องรัน login_facebook.py ใหม่ก่อนใช้งาน linkcrawler.py อีกครั้ง
หากรายการไหนต้อง Login บัญชี Facebook ถึงจะเห็น Live Video)

วิธีใช้: python logout_facebook.py
"""
import os
import shutil
import time

from selenium.webdriver.common.by import By

from modules.utilities import FACEBOOK_PROFILE_DIR, create_stealth_chrome_driver

ACCOUNT_MENU_XPATHS = [
    "//div[@aria-label='บัญชีของคุณ']",
    "//div[@aria-label='Your profile']",
    "//div[@aria-label='Account']",
    "//div[@aria-label='บัญชี']",
]

LOGOUT_XPATHS = [
    "//span[text()='ออกจากระบบ']",
    "//span[text()='Log Out']",
    "//span[text()='Log out']",
    "//div[@aria-label='ออกจากระบบ']",
    "//div[@aria-label='Log Out']",
]


def try_click_facebook_logout(driver) -> bool:
    """
    พยายามกดปุ่ม Logout จากเมนูบัญชีบนหน้าเว็บ Facebook (Best Effort)
    หากหา element ไม่เจอ (เช่น Facebook เปลี่ยน UI) จะคืนค่า False แล้วปล่อยให้ main()
    ล้าง Cookies/ลบ Profile ทิ้งแทนอยู่ดี
    """
    try:
        driver.get("https://www.facebook.com/")
        time.sleep(3)

        for xp in ACCOUNT_MENU_XPATHS:
            for el in driver.find_elements(By.XPATH, xp):
                if el.is_displayed():
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(1)
                    break

        for xp in LOGOUT_XPATHS:
            for el in driver.find_elements(By.XPATH, xp):
                if el.is_displayed():
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(2)
                    return True
    except Exception as e:
        print(f"[Logout Facebook] ไม่สามารถกด Logout ผ่านหน้าเว็บได้: {e}")

    return False


def main():
    if not os.path.isdir(FACEBOOK_PROFILE_DIR):
        print(f"[Logout Facebook] ไม่พบ Chrome Profile ที่: {FACEBOOK_PROFILE_DIR} (ยังไม่เคย Login)")
        return

    print("=" * 70)
    print(f"[Logout Facebook] กำลังเปิด Chrome โดยใช้ Profile ที่: {FACEBOOK_PROFILE_DIR}")
    driver = create_stealth_chrome_driver(headless=False)

    try:
        logged_out = try_click_facebook_logout(driver)
        if logged_out:
            print("[Logout Facebook] ✅ กด Logout บนหน้าเว็บ Facebook สำเร็จ")
        else:
            print("[Logout Facebook] ⚠️ ไม่พบปุ่ม Logout บนหน้าเว็บ (จะล้าง Cookies/Profile ทิ้งแทน)")
        driver.delete_all_cookies()
    finally:
        driver.quit()

    # หน่วงเวลาสั้นๆ ให้ Chrome ปล่อย Lock ไฟล์ใน Profile Directory ก่อนลบ (โดยเฉพาะบน Windows)
    time.sleep(1.5)

    print(f"[Logout Facebook] กำลังลบ Chrome Profile ทิ้งที่: {FACEBOOK_PROFILE_DIR}")
    shutil.rmtree(FACEBOOK_PROFILE_DIR, ignore_errors=True)

    if os.path.isdir(FACEBOOK_PROFILE_DIR):
        print("[Logout Facebook] ⚠️ ลบ Profile ไม่สำเร็จทั้งหมด (อาจมีไฟล์ถูก Lock อยู่) กรุณาลองรันใหม่อีกครั้ง")
    else:
        print("[Logout Facebook] ✅ ล้างข้อมูล Chrome Profile เรียบร้อยแล้ว")
    print("[Logout Facebook] ต้องรัน login_facebook.py ใหม่ก่อนใช้งาน linkcrawler.py ครั้งถัดไป")
    print("=" * 70)


if __name__ == "__main__":
    main()
