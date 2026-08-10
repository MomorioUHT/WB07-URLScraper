/**
 * WB07 URL Scraper - Google Apps Script Web App
 * ผูก script นี้ไว้กับ Google Sheet ที่ใช้งานจริงโดยตรง (Extensions > Apps Script)
 * ฝั่ง Python เรียก Web App นี้ผ่าน HTTP เท่านั้น ไม่ต้องใช้ SHEET_ID / GID อีกต่อไป
 *
 * Deploy วิธีนี้:
 * 1. เปิด Google Sheet ที่ใช้งานอยู่ -> Extensions > Apps Script
 * 2. วางโค้ดนี้ทับไฟล์ Code.gs (หรือสร้างไฟล์ใหม่ชื่อ App.gs แล้ววางที่นี่)
 * 3. หากตารางไม่ได้อยู่ชีท (tab) แรกของไฟล์ ให้ตั้งชื่อชีทในตัวแปร SHEET_NAME ด้านล่าง
 * 4. (แนะนำ) ตั้งค่า Secret Token: Project Settings > Script Properties -> เพิ่ม key "API_TOKEN" ค่าใดก็ได้
 * 5. Deploy > New deployment > Type: Web app
 *    - Execute as: Me
 *    - Who has access: Anyone with the link
 * 6. คัดลอก Web app URL ที่ได้ (ลงท้ายด้วย /exec) ไปใส่ใน .env เป็น POST_SCRIPT_API
 */

// ชื่อชีท (tab) ที่ใช้งานจริง ปล่อยว่าง '' ถ้าต้องการใช้ชีทแรกของไฟล์เสมอ
const SHEET_NAME = '';

// ตำแหน่งแถวเริ่มต้นของข้อมูล (ตรงกับ start_row=6 ใน linkcrawler.py)
const START_ROW = 6;

// คอลัมน์ข้อมูลตารางเวลา (อ่านอย่างเดียว)
const COL_DATE = 1;   // A
const COL_TIME = 2;   // B
const COL_TITLE = 3;  // C

// คอลัมน์ผลลัพธ์ลิงก์ (เขียนกลับ)
const COL_FB = 11;    // K
const COL_YT = 13;    // M
const COL_X = 14;     // N

/**
 * ตั้งค่า Token ป้องกันการเรียกจากคนนอก (ไม่บังคับ)
 * หากไม่ต้องการใช้ ให้ลบ Script Property "API_TOKEN" ทิ้ง หรือปล่อยว่างไว้
 */
function checkToken_(token) {
  const expected = PropertiesService.getScriptProperties().getProperty('API_TOKEN');
  if (!expected) return true; // ไม่ได้ตั้งค่า token ไว้ -> ไม่ตรวจสอบ
  return token === expected;
}

function getSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return SHEET_NAME ? ss.getSheetByName(SHEET_NAME) : ss.getSheets()[0];
}

/**
 * ค้นหาแถวที่ วันที่ + เวลา + ชื่อรายการ ตรงกันทุกช่องแบบเป๊ะๆ
 * ใช้เป็น fallback เมื่อ row ที่ส่งมาไม่ตรงกับข้อมูลที่คาดไว้ (เช่น แถวเลื่อนตำแหน่ง)
 * และป้องกันกรณีชื่อรายการซ้ำกันแต่คนละวัน เช่น "ทันข่าว 06.00 น." ของวันที่ต่างกัน
 */
function findRowByMatch_(sheet, date, time, title) {
  const lastRow = sheet.getLastRow();
  if (lastRow < START_ROW) return null;

  const numRows = lastRow - START_ROW + 1;
  const values = sheet.getRange(START_ROW, COL_DATE, numRows, 3).getValues();

  for (var i = 0; i < values.length; i++) {
    const d = formatCellValue_(values[i][0]);
    const t = formatCellValue_(values[i][1]);
    const ti = formatCellValue_(values[i][2]);
    if (d === date && t === time && ti === title) {
      return START_ROW + i;
    }
  }
  return null;
}

function formatCellValue_(v) {
  if (v instanceof Date) {
    return Utilities.formatDate(v, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  }
  return (v === null || v === undefined) ? '' : String(v).trim();
}

function jsonOutput_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * GET API - ดึงข้อมูลตาราง (A: วันที่, B: เวลา, C: ชื่อรายการ) ตั้งแต่แถว START_ROW
 * เรียกใช้: GET {WEB_APP_URL}?token=xxxx
 * Response: { status: "ok", count: N, data: [{ row, date, time, title }, ...] }
 */
function doGet(e) {
  try {
    const params = (e && e.parameter) ? e.parameter : {};

    if (!checkToken_(params.token)) {
      return jsonOutput_({ status: 'error', message: 'invalid token' });
    }

    const sheet = getSheet_();
    const lastRow = sheet.getLastRow();
    const data = [];

    if (lastRow >= START_ROW) {
      const numRows = lastRow - START_ROW + 1;
      const values = sheet.getRange(START_ROW, COL_DATE, numRows, 3).getValues();

      values.forEach(function (r, idx) {
        const date = formatCellValue_(r[0]);
        const time = formatCellValue_(r[1]);
        const title = formatCellValue_(r[2]);

        // ข้ามแถวที่ไม่มีชื่อรายการ (คอลัมน์ C) เหมือน logic ฝั่ง Python
        if (!title) return;

        data.push({
          row: START_ROW + idx,
          date: date,
          time: time,
          title: title
        });
      });
    }

    return jsonOutput_({ status: 'ok', count: data.length, data: data });
  } catch (err) {
    return jsonOutput_({ status: 'error', message: err.message });
  }
}

/**
 * POST API - เขียนผลลัพธ์ลิงก์กลับลงแถวที่ตรงกัน (K=Facebook, M=YouTube, N=X)
 *
 * ก่อนเขียนจริง จะตรวจสอบวันที่ + เวลา + ชื่อรายการ ของแถวที่ระบุก่อนเสมอ (ถ้าส่งมาด้วย)
 * เพื่อป้องกันการเขียนผิดแถว เช่น กรณีชื่อรายการซ้ำกันแต่คนละวัน
 * ("2026-08-09  06:00  ทันข่าว 06.00 น." กับรายการชื่อเดียวกันของวันอื่น)
 * หากแถวที่ระบุไม่ตรง จะค้นหาแถวที่ตรงจริงให้อัตโนมัติ (findRowByMatch_)
 * และถ้าหาไม่เจอเลย จะข้ามรายการนั้น (ไม่เขียนทับแถวผิด)
 *
 * เรียกใช้: POST {WEB_APP_URL}
 * Body (แถวเดียว):
 *   { "token": "xxxx", "row": 6, "date": "2026-08-09", "time": "06:00", "title": "ทันข่าว 06.00 น.",
 *     "facebook_url": "...", "youtube_url": "...", "x_url": "..." }
 * Body (หลายแถวพร้อมกัน):
 *   { "token": "xxxx", "items": [ { "row": 6, "date": "...", "time": "...", "title": "...", "facebook_url": "..." }, ... ] }
 * Response: { status: "ok", updated: [{ row, status, reason? }, ...] }
 */
function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);

    if (!checkToken_(body.token)) {
      return jsonOutput_({ status: 'error', message: 'invalid token' });
    }

    const sheet = getSheet_();
    const items = Array.isArray(body.items) ? body.items : [body];
    const results = [];

    items.forEach(function (item) {
      var row = parseInt(item.row, 10);
      const expectedDate = item.date !== undefined ? formatCellValue_(item.date) : null;
      const expectedTime = item.time !== undefined ? formatCellValue_(item.time) : null;
      const expectedTitle = item.title !== undefined ? formatCellValue_(item.title) : null;
      const hasExpectedInfo = expectedDate && expectedTime && expectedTitle;

      if (hasExpectedInfo) {
        const rowValues = (row && row >= START_ROW)
          ? sheet.getRange(row, COL_DATE, 1, 3).getValues()[0]
          : null;
        const rowMatches = rowValues &&
          formatCellValue_(rowValues[0]) === expectedDate &&
          formatCellValue_(rowValues[1]) === expectedTime &&
          formatCellValue_(rowValues[2]) === expectedTitle;

        if (!rowMatches) {
          const foundRow = findRowByMatch_(sheet, expectedDate, expectedTime, expectedTitle);
          if (foundRow) {
            row = foundRow;
          } else {
            results.push({
              row: item.row,
              status: 'skipped',
              reason: 'date/time/title ไม่ตรงกับข้อมูลในชีท ไม่พบแถวที่ตรงจริง จึงไม่เขียนทับ'
            });
            return;
          }
        }
      }

      if (!row || row < START_ROW) {
        results.push({ row: item.row, status: 'skipped', reason: 'invalid row' });
        return;
      }

      if (item.facebook_url !== undefined) {
        sheet.getRange(row, COL_FB).setValue(item.facebook_url);
      }
      if (item.youtube_url !== undefined) {
        sheet.getRange(row, COL_YT).setValue(item.youtube_url);
      }
      if (item.x_url !== undefined) {
        sheet.getRange(row, COL_X).setValue(item.x_url);
      }

      results.push({ row: row, status: 'ok' });
    });

    return jsonOutput_({ status: 'ok', updated: results });
  } catch (err) {
    return jsonOutput_({ status: 'error', message: err.message });
  }
}
