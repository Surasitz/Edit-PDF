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
    "📝 แปลงเป็น Word (.docx)...": "📝 Convert to Word (.docx)...",
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
    # ----- PDF -> Word -----
    "แปลง PDF เป็น Word": "Convert PDF to Word",
    "เลือกรูปแบบไฟล์ Word ที่ต้องการ": "Choose the kind of Word file you want",
    "คงหน้าตาเดิมทุกอย่าง (แนะนำ)": "Keep the original look (recommended)",
    "ตัวอักษร ตำแหน่ง ตาราง และฟอร์ม อยู่ตรงเดิมเป๊ะ\n"
    "เหมาะกับหนังสือราชการ แบบฟอร์ม ใบเสร็จ ที่ต้องเหมือนต้นฉบับ":
        "Text, positions, tables and forms land exactly where they were.\n"
        "Best for official letters, forms and receipts that must match the original.",
    "พิมพ์แก้ต่อได้ง่าย (ข้อความไหลต่อกัน)": "Easy to keep writing in (flowing text)",
    "ได้ย่อหน้าปกติแบบที่พิมพ์เองใน Word แก้ไขสะดวกกว่า\n"
    "แต่หน้าที่มีหลายคอลัมน์หรือฟอร์มซับซ้อนอาจเลื่อนได้":
        "Ordinary paragraphs like ones you would type yourself, much easier to edit,\n"
        "but multi-column pages and complicated forms may shift.",
    "แปลงตารางที่มีเส้นให้เป็นตารางของ Word":
        "Turn ruled tables into real Word tables",
    "หน้าที่จะแปลง:": "Pages to convert:",
    "เว้นว่าง = ทั้งไฟล์ (%d หน้า) — หรือระบุ เช่น 1-3,5":
        "Blank = whole file (%d pages) — or list them, e.g. 1-3,5",
    "ฟอนต์และขนาดตัวอักษรเดิมถูกเก็บไว้ครบ รวมภาษาไทย\n"
    "หน้าที่เป็นรูปสแกน จะถูกใส่เป็นรูปภาพให้แทน":
        "The original fonts and sizes are kept, Thai included.\n"
        "Scanned pages come across as pictures.",
    "แปลงเลย": "Convert",
    "บันทึกเป็นไฟล์ Word": "Save as a Word file",
    "กำลังแปลงเป็น Word...": "Converting to Word...",
    "ยกเลิก": "Cancel",
    "ยกเลิกการแปลงแล้ว": "Conversion cancelled.",
    "แปลงเป็น Word ไม่สำเร็จ:\n%s": "Could not convert to Word:\n%s",
    "แปลงเป็น Word แล้ว %d หน้า: %s ✓": "Converted %d pages to Word: %s ✓",
    "รูปแบบหน้าไม่ถูกต้องหรืออยู่นอกช่วง":
        "That page range is not valid or is out of range.",
    "แปลงเสร็จแล้ว แต่หน้า %s%s อ่านตัวอักษรจากไฟล์ PDF "
    "ไม่ได้ (ไฟล์ต้นฉบับไม่ได้ฝังตารางรหัสตัวอักษรมา)\n\n"
    "จึงใส่เป็นรูปภาพให้แทน เพื่อไม่ให้ได้ข้อความที่เพี้ยน":
        "Done — but the characters on page %s%s could not be read out of the PDF "
        "(the original has no usable character map embedded).\n\n"
        "Those pages went in as pictures, so you don't get garbled text.",
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
    # ----- compress PDF -----
    "🗜 บีบอัด PDF ลดขนาดไฟล์ (ทีเดียวหลายไฟล์)...":
        "🗜 Compress PDF - shrink file size (many at once)...",
    "บีบอัด PDF (ลดขนาดไฟล์)": "Compress PDF (shrink file size)",
    "ลดขนาดไฟล์ PDF ได้ทีละหลายไฟล์": "Shrink several PDF files in one go",
    "ลากไฟล์ PDF มาวางตรงนี้ หรือกดปุ่ม 'เพิ่มไฟล์'\n"
    "ทุกอย่างทำในเครื่องคุณ ไม่มีการอัปโหลดไฟล์ออกไปไหน และไฟล์ต้นฉบับไม่ถูกแก้":
        "Drop PDF files here, or use 'Add files'.\n"
        "Everything runs on your machine - nothing is uploaded, and the "
        "originals are never modified.",
    "ไฟล์": "File",
    "ขนาดเดิม": "Before",
    "ขนาดใหม่": "After",
    "ผลลัพธ์": "Result",
    "➕ เพิ่มไฟล์...": "➕ Add files...",
    "เอาออก": "Remove",
    "ล้างรายการ": "Clear list",
    "รวม %d ไฟล์ • %s": "%d files • %s",
    "เลือกไฟล์ PDF (เลือกได้หลายไฟล์)": "Choose PDF files (more than one is fine)",
    "ระดับการบีบอัด:": "Compression level:",
    "คุณภาพสูง": "High quality",
    "สมดุล (แนะนำ)": "Balanced (recommended)",
    "เล็กที่สุด": "Smallest",
    "ภาพยังคมเกือบเท่าเดิม เหมาะกับงานที่ต้องพิมพ์ออกมาชัดๆ (ลดขนาดได้น้อยกว่าแบบอื่น)":
        "Images stay almost as sharp - for documents you need to print "
        "crisply (saves less than the other levels).",
    "ลดขนาดได้มาก ภาพยังอ่านง่ายทั้งบนจอและตอนพิมพ์ — เหมาะกับเอกสารสแกนทั่วไป":
        "A big saving with images still easy to read on screen and in print - "
        "right for everyday scans.",
    "ไฟล์เล็กที่สุด เหมาะกับการส่งอีเมลหรืออัปโหลดเข้าระบบ ที่จำกัดขนาดไฟล์ (ภาพจะหยาบลงบ้าง)":
        "The smallest file, for e-mail or upload limits (images get a little "
        "rough).",
    "แปลงรูปในไฟล์เป็นขาวดำ (เอกสารสแกนขาวดำจะเล็กลงอีกมาก)":
        "Turn the images grey-scale (a black-and-white scan gets much smaller)",
    "ตัดฟอนต์ที่ฝังมาให้เหลือเฉพาะตัวอักษรที่ใช้จริง":
        "Trim embedded fonts down to the characters actually used",
    "ช่วยได้มากกับหนังสือราชการที่ฝังฟอนต์ไทยมาทั้งชุด\n"
    "ถ้าจะเอาไฟล์ผลลัพธ์ไปพิมพ์ข้อความเพิ่มทีหลัง แนะนำให้เอาเครื่องหมายออก":
        "A big win for official documents that embed whole Thai font "
        "families.\nUntick it if you plan to keep typing in the result.",
    "บันทึกไว้โฟลเดอร์เดียวกับไฟล์ต้นฉบับ": "Save next to the original files",
    "โฟลเดอร์อื่น:": "Another folder:",
    "เลือก...": "Browse...",
    "เลือกโฟลเดอร์ปลายทาง": "Choose the destination folder",
    "บีบอัดเลย": "Compress",
    "ปิด": "Close",
    "หยุด": "Stop",
    "กำลังหยุด...": "Stopping...",
    "📂 เปิดโฟลเดอร์ผลลัพธ์": "📂 Open the results folder",
    "รอคิว": "Queued",
    "กำลังบีบอัด...": "Compressing...",
    "ยกเลิกแล้ว": "Cancelled",
    "ไฟล์มีรหัสผ่าน": "Password-protected",
    "ไม่สำเร็จ": "Failed",
    "เล็กที่สุดแล้ว": "Already smallest",
    "ลดลง %.0f%%": "%.0f%% smaller",
    "ยังไม่ได้บีบอัดไฟล์ใด": "No file was compressed",
    "เสร็จแล้ว %d ไฟล์ • จาก %s เหลือ %s (ประหยัด %s / %.0f%%)":
        "Done: %d files • %s down to %s (saved %s / %.0f%%)",
    "ไฟล์ที่เปิดอยู่ยังมีการแก้ไขที่ไม่ได้บันทึก\n"
    "การบีบอัดจะใช้ไฟล์ที่บันทึกไว้บนเครื่อง\n\n"
    "ต้องการบันทึกก่อนหรือไม่?":
        "The open file has unsaved changes.\n"
        "Compression works on the copy saved on disk.\n\nSave it first?",
    "บีบอัดแล้ว %d ไฟล์ — เล็กลง %.0f%% ✓":
        "Compressed %d files - %.0f%% smaller ✓",
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
