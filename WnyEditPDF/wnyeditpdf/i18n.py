# -*- coding: utf-8 -*-
"""Tiny two-language (Thai / English) lookup table for the UI chrome.

Keys are the Thai source strings; values are the English translations.
`tr(text, lang)` returns the translation when lang == "en" and the string is
known, otherwise it returns the original text unchanged. This keeps the call
sites readable (the Thai label is right there in the code) and means any string
we forget to translate simply stays in Thai instead of crashing.
"""

EN = {
    # ----- menu bar -----
    "ไฟล์(&F)": "File(&F)",
    "แก้ไข(&E)": "Edit(&E)",
    "หน้า(&P)": "Page(&P)",
    "เครื่องมือ(&T)": "Tools(&T)",
    "ลายเซ็น(&S)": "Signature(&S)",
    "ช่วยเหลือ(&H)": "Help(&H)",
    # ----- File menu -----
    "เปิด...": "Open...",
    "เปิดไฟล์ล่าสุด": "Recent files",
    "บันทึก": "Save",
    "บันทึกเป็น...": "Save as...",
    "บันทึกแบบมีรหัสผ่าน...": "Save with password...",
    "รวม PDF (เลือกหน้า + ตำแหน่งแทรก)...": "Merge PDF (pick pages + position)...",
    "ส่งออกหน้านี้เป็น PNG...": "Export this page as PNG...",
    "ดึงข้อความทั้งไฟล์เป็น .txt...": "Extract all text to .txt...",
    "ออกจากโปรแกรม": "Quit",
    # ----- Edit menu -----
    "↶ เลิกทำ (Undo)": "↶ Undo",
    "↷ ทำซ้ำ (Redo)": "↷ Redo",
    "ค้นหา / แทนที่...": "Find / Replace...",
    # ----- Page menu -----
    "หมุน 90° ตามเข็ม": "Rotate 90° clockwise",
    "หมุน 90° ทวนเข็ม": "Rotate 90° counter-clockwise",
    "เลื่อนหน้านี้ขึ้น (ไปก่อนหน้า)": "Move page up",
    "เลื่อนหน้านี้ลง (ไปทีหลัง)": "Move page down",
    "ลบหน้านี้": "Delete this page",
    "แทรกหน้าว่างหลังหน้านี้": "Insert blank page after this",
    "แยกช่วงหน้าเป็นไฟล์ใหม่...": "Split page range to new file...",
    # ----- Tools menu -----
    "🖼 แทรกรูปภาพ (PNG/JPG)...": "🖼 Insert image (PNG/JPG)...",
    "🔖 แสตมป์สัญลักษณ์": "🔖 Symbol stamps",
    "✔️  เครื่องหมายถูก": "✔️  Check mark",
    "❌  กากบาท": "❌  Cross mark",
    "⚫  จุด": "⚫  Dot",
    "⭕  วงกลมล้อมรอบ": "⭕  Circle around",
    "➖  ขีดเส้น/ขีดฆ่า": "➖  Strike-through",
    "💧 ใส่ลายน้ำทุกหน้า...": "💧 Add watermark to all pages...",
    "⬜ ปิดทับพื้นที่ (ลากคลุม)": "⬜ White-out area (drag)",
    "🔗 เพิ่มลิงก์ (ลากคลุมพื้นที่)": "🔗 Add link (drag an area)",
    "🔗 ใส่ลิงก์บนข้อความ (คลิกข้อความ)": "🔗 Link on text (click the text)",
    "🔢 ใส่เลขหน้าอัตโนมัติ...": "🔢 Add page numbers...",
    "📋 ตราประทับข้อความ (สำเนาถูกต้อง/ด่วน/วันที่)...":
        "📋 Text stamp (Certified True Copy / Urgent / date)...",
    "🔳 สร้าง QR Code...": "🔳 Create QR code...",
    # ----- link manage dialog -----
    "🕘 ประวัติเวอร์ชัน (กู้คืนไฟล์เก่า)...": "🕘 Version history (restore older file)...",
    "บันทึกทับไฟล์ต้นฉบับ?": "Overwrite the original file?",
    "กำลังจะบันทึกทับไฟล์ต้นฉบับ\nข้อมูลเดิมจะถูกแทนที่": "You are about to overwrite the original file.\nThe existing data will be replaced.",
    "แนะนำให้บันทึกเป็นไฟล์ใหม่ เพื่อเก็บต้นฉบับไว้": "We recommend saving as a new file so the original is kept.",
    "บันทึกเป็นไฟล์ใหม่ (แนะนำ)": "Save as a new file (recommended)",
    "บันทึกทับ (สำรองอัตโนมัติ)": "Overwrite (auto-backup kept)",
    "ประวัติเวอร์ชัน": "Version history",
    "ยังไม่มีเวอร์ชันสำรองของไฟล์นี้\n(ระบบจะสำรองให้อัตโนมัติเมื่อคุณบันทึกทับไฟล์เดิม)": "No backup versions of this file yet.\n(A backup is made automatically when you overwrite the original.)",
    "เลือกเวอร์ชันที่ต้องการเปิดดู/กู้คืน:": "Choose a version to open / restore:",
    "เปิดเวอร์ชันเก่าแล้ว — ถ้าต้องการใช้ ให้ 'บันทึกเป็น...' เป็นไฟล์ใหม่ (ต้นฉบับปัจจุบันยังอยู่)": "Opened an older version - use 'Save As...' to keep it as a new file (the current original is untouched).",
    "เปิดไฟล์ PDF เพื่อเริ่มใช้งาน\n\n📂 กด Ctrl+O  หรือ  ลากไฟล์ PDF มาวางที่นี่": "Open a PDF to get started\n\n📂 Press Ctrl+O  or  drag a PDF file here",
    # ----- scan enhancement -----
    "🔆 ปรับแต่งรูปสแกน (สว่าง/คมชัด/แก้เอียง)...": "🔆 Enhance scan (brightness / contrast / deskew)...",
    "ปรับแต่งรูปสแกน": "Enhance scan",
    "ปรับเอกสารที่สแกนมามืดหรือเอียง\n(ใช้กับหน้าที่เป็นรูปสแกนเท่านั้น)": "Fix scans that came out dark or crooked.\n(For scanned pages only.)",
    "ความสว่าง": "Brightness",
    "ความคมชัด": "Contrast",
    "แก้เอียง (องศา)": "Deskew (degrees)",
    "เคล็ดลับ: เอกสารมืด → เพิ่มความสว่าง +30 และความคมชัด +25\nเอกสารเอียง → ปรับแก้เอียงทีละ 0.5°": "Tip: dark page -> brightness +30, contrast +25.\nCrooked page -> nudge deskew by 0.5\u00b0 at a time.",
    "หน้านี้ไม่ใช่หน้าสแกน (มีข้อความจริงอยู่)\n\nถ้าปรับแต่ง ข้อความจะกลายเป็นรูปภาพ แก้ไขข้อความไม่ได้อีก\nต้องการทำต่อหรือไม่?": "This page is not a scan - it contains real text.\n\nEnhancing it turns the text into pixels, so it can no longer be edited.\nContinue anyway?",
    "ปรับแต่งรูปสแกนแล้ว ✓ (Ctrl+Z ย้อนกลับได้)": "Scan enhanced \u2713 (Ctrl+Z to undo)",
    "ปรับแต่งไม่สำเร็จ": "Could not enhance the scan",
    "จัดการลิงก์": "Manage link",
    "แก้ไขลิงก์": "Edit link",
    "เอาลิงก์ออก": "Remove link",
    # ----- highlight colour dropdown -----
    "เหลือง": "Yellow", "เขียว": "Green", "ฟ้า": "Blue",
    "ชมพู": "Pink", "ส้ม": "Orange",
    "🎨 เลือกสีอื่น...": "🎨 Pick another colour...",
    # ----- pen colour dropdown -----
    "น้ำเงิน": "Blue", "ดำ": "Black", "แดง": "Red",
    # ----- comment style dropdown -----
    "📌 โน้ต (คลิกวาง)": "📌 Note (click to place)",
    "➶ ลูกศรชี้ (ลาก)": "➶ Arrow (drag)",
    "▭ กล่องข้อความ (ลาก)": "▭ Text box (drag)",
    # ----- Signature menu -----
    "✍️ สร้าง/เลือกลายเซ็น (วาด / นำเข้ารูป / พิมพ์ชื่อ)...":
        "✍️ Create/pick signature (draw / import / type)...",
    # ----- Help menu -----
    "เกี่ยวกับ": "About",
    # ----- toolbar row 1 -----
    "📂 เปิด": "📂 Open",
    "💾 บันทึก": "💾 Save",
    "พอดีหน้า": "Fit page",
    "🔎 ค้นหา/แทนที่": "🔎 Find/Replace",
    # ----- toolbar row 2: modes -----
    "🖱 เลือก": "🖱 Select",
    "✏️ แก้ข้อความ": "✏️ Edit text",
    "✥ ขยับ/ย่อขยาย": "✥ Move/Resize",
    "🗑 ลบ": "🗑 Delete",
    "＋ เพิ่มข้อความ": "＋ Add text",
    "🖍 ไฮไลท์": "🖍 Highlight",
    "🖊 ปากกา": "🖊 Pen",
    "✍️ ลายเซ็น": "✍️ Signature",
    "🖼 รูปภาพ": "🖼 Image",
    "💬 คอมเมนต์": "💬 Comment",
    "⬜ ปิดทับ": "⬜ White-out",
    "🖍 สี ■": "🖍 Colour ■",
    # ----- mode tooltips -----
    "โหมดดู / คลิกไอคอนคอมเมนต์เพื่ออ่าน": "View mode / click a comment icon to read",
    "คลิกข้อความเดิมเพื่อแก้ไข (เลือกฟอนต์/ขนาด/สีในกล่อง)":
        "Click existing text to edit (font/size/colour in the box)",
    "ลากข้อความหรือรูปไปวางที่ใหม่ / ลากมุมเพื่อย่อ-ขยาย":
        "Drag text or image to move / drag a corner to resize",
    "คลิกข้อความ รูป ลายเซ็น เส้นปากกา หรือคอมเมนต์ เพื่อลบ":
        "Click text, image, signature, pen stroke or comment to delete",
    "คลิกตำแหน่งว่างเพื่อพิมพ์ข้อความใหม่": "Click an empty spot to type new text",
    "ลากคลุมข้อความเพื่อไฮไลท์": "Drag over text to highlight",
    "ลากเมาส์วาดเส้นอิสระ (วงกลม/ขีดเส้นใต้เอกสาร)":
        "Drag to draw freehand (circle / underline)",
    "เลือก/สร้างลายเซ็น แล้วคลิกวางบนหน้า":
        "Pick/create a signature then click to place it",
    "เลือกรูป แล้วคลิกวางบนหน้า": "Pick an image then click to place it",
    "คลิกบนหน้าเพื่อวางโน้ต / คลิกไอคอนเดิมเพื่อแก้":
        "Click the page to drop a note / click an icon to edit",
    "ลากคลุมพื้นที่เพื่อลบ/ปิดทับด้วยสีขาว":
        "Drag over an area to white it out",
    "เลือกสีไฮไลท์": "Highlight colour",
    # ----- language button -----
    "ภาษา: ไทย": "Language: English",
    # ----- welcome / common status -----
    "ยินดีต้อนรับสู่ WnyEditPDF — เปิดไฟล์ PDF เพื่อเริ่มใช้งาน (Ctrl+O)":
        "Welcome to WnyEditPDF — open a PDF to get started (Ctrl+O)",
    "กรุณาเปิดไฟล์ PDF ก่อน": "Please open a PDF first.",
}


def tr(text, lang):
    """Return the English translation when lang == 'en', else the original."""
    if lang == "en":
        return EN.get(text, text)
    return text
