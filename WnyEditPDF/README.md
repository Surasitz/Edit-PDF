# WnyEditPDF

A free, offline desktop **PDF reader & editor** with first-class Thai-language
support, built with Python + PyQt6 + PyMuPDF. Everything runs locally on your
machine — no internet, no accounts, no limits, no data ever leaves your computer.

โปรแกรมอ่านและแก้ไข PDF บนเดสก์ท็อป ฟรี ใช้งานออฟไลน์ 100% รองรับภาษาไทยเต็มรูปแบบ
ทำงานบนเครื่องคุณล้วนๆ ไม่ต่อเน็ต ไม่ต้องสมัคร ไม่มีลิมิต ข้อมูลไม่ออกจากเครื่อง

---

## English

### Features
- **Text editing** — edit, move, resize, add and delete text while keeping the
  original font, size, colour, **bold/italic** and position. Overlapping text is
  handled surgically so neighbouring words are never eaten or merged.
- **Bold / italic** — a real bold/italic toggle when adding or editing text;
  faux-bold is synthesised when the font has no dedicated bold file.
- **Highlight** with a selectable colour.
- **Signatures** — draw, import an image, or type your name; save a whole
  **gallery** of reusable signatures that persist between sessions.
- **Images & symbol stamps** (check, cross, dot, circle, dash), free-hand
  **pen**, **comments** (draggable sticky notes), **white-out**, and **watermarks**.
- **Find & Replace** across the whole file, keeping each hit's original font.
  Matches are highlighted live; jump between them with the prev/next buttons.
- **Page management** — rotate, delete, insert, reorder (drag thumbnails or
  right-click), **merge** selected pages from another file at any position, and
  **split** a page range to a new file.
- **PDF → Word (.docx)** that keeps the text intact. Every run is written with
  an explicit complex-script font, size and `bidi` language, which is what Word
  actually uses to render Thai — miss it and a 16 pt TH SarabunPSK document
  opens as 11 pt Calibri. Thai that the PDF stored in pieces (a decomposed
  SARA AM, a tone mark filed before its vowel) is put back together. Choose
  between *keep the original look* (every line placed exactly, so tables and
  forms hold) and *easy to keep writing in* (flowing paragraphs, with ruled
  tables converted to real Word tables). Pages whose characters cannot be
  decoded at all go in as pictures and are reported, rather than becoming
  gibberish.
- **Compress PDFs, many at once** — drop a pile of files in one window, pick
  one setting, and let it run: each row reports what it went from, what it came
  to, and the percentage saved. Images are re-rendered at the resolution they
  are actually displayed at (a 600 dpi scan on A4 carries four times the pixels
  a printer will use) and re-encoded, with optional grey-scale and font
  subsetting. Everyday scans typically lose 60–80% of their weight. The
  originals are never written to — results go to `name_compressed.pdf` — and
  every result is opened and page-counted before it is accepted, so a file that
  cannot be improved comes back untouched rather than broken. And it is all
  local: the documents you would never be allowed to upload to a web
  "compress PDF" service never leave the machine.
- **Export** to PDF, PNG, JPG or plain text; **AES-256 password** protection.
- Nudge the selected text/image by **1 pt with the arrow keys** (Shift = 5 pt).
- Full **Undo/Redo**, and a **Thai / English** UI you can switch with the flag
  button (top-right).

### Requirements
- Python 3.10+
- `pip install -r requirements.txt` (PyQt6, PyMuPDF)

### Run
```bash
pip install -r requirements.txt
python main.py
```

### Build a standalone .exe (Windows)
```bat
pip install pyinstaller
pyinstaller --onefile --windowed --name WnyEditPDF ^
    --icon wnyeditpdf/assets/logo.ico ^
    --add-data "fonts;fonts" ^
    --add-data "wnyeditpdf/assets;wnyeditpdf/assets" ^
    --hidden-import qrcode ^
    main.py
```
On macOS/Linux replace `;` with `:` and `^` with `\`. The result is
`dist/WnyEditPDF.exe`, which you can copy to any machine. (See `BUILD.md`.)

> Windows SmartScreen may warn that the publisher is unknown because the binary
> is not code-signed. It is safe — click **More info → Run anyway**.

### Project layout
```
WnyEditPDF/
├── main.py                 # entry point
├── requirements.txt
├── pyproject.toml          # package metadata
├── BUILD.md                # packaging instructions
├── CHANGELOG.md
├── LICENSE                 # AGPL-3.0 (matches PyMuPDF/PyQt6)
├── THIRD_PARTY_LICENSES.md
├── wnyeditpdf/             # main application package
│   ├── config.py           # constants, colours, modes, stylesheet
│   ├── i18n.py             # Thai/English UI strings
│   ├── fonts.py            # bundled-font manager
│   ├── document.py         # PdfDocument — all PDF operations (PyMuPDF)
│   ├── docx_export.py      # PDF → Word (.docx) writer, no dependencies
│   ├── compress.py         # PDF size reduction (images / fonts / structure)
│   ├── widgets.py          # PageView, dialogs, thumbnail list, search bar
│   ├── window.py           # MainWindow — menus, toolbars, event wiring
│   ├── assets/             # logo.png / logo.ico
│   └── vendor/qrcode/      # bundled QR library (no external install needed)
└── fonts/                  # 59 bundled Thai .ttf fonts (TH Sarabun family, etc.)
```


### Licence note
PyQt6 is GPL and PyMuPDF is AGPL. You may use this freely inside an
organisation. If you distribute it commercially you must comply with those
licences (open your source, or buy commercial licences).

---

## ภาษาไทย

### ความสามารถ
- **แก้ไขข้อความ** — แก้/ขยับ/ย่อขยาย/เพิ่ม/ลบ โดยคงฟอนต์ ขนาด สี **ตัวหนา/เอียง**
  และตำแหน่งเดิม จัดการข้อความที่ทับกันแบบผ่าตัด คำข้างเคียงไม่หายหรือรวมกัน
- **ตัวหนา/เอียง** — มีปุ่มทำตัวหนา/เอียงตอนเพิ่มหรือแก้ข้อความ ถ้าฟอนต์ไม่มีไฟล์หนา
  ก็สร้างตัวหนาเทียมให้
- **ไฮไลท์** เลือกสีได้
- **ลายเซ็น** — วาดเอง / นำเข้ารูป / พิมพ์ชื่อ และเก็บเป็น**คลังลายเซ็นหลายอัน**
  ใช้ซ้ำได้ ค้างอยู่แม้ปิดโปรแกรม
- **รูปภาพ & แสตมป์สัญลักษณ์** (ถูก กากบาท จุด วงกลม ขีด), **ปากกา**วาดอิสระ,
  **คอมเมนต์** (โน้ตลากย้ายได้), **ปิดทับ**, และ **ลายน้ำ**
- **ค้นหา-แทนที่**ทั้งไฟล์ คงฟอนต์เดิมของแต่ละจุด ไฮไลท์คำที่เจอ เลื่อนดูก่อนหน้า/ถัดไป
- **จัดการหน้า** — หมุน ลบ แทรก สลับลำดับ (ลากภาพย่อหรือคลิกขวา), **รวม**เฉพาะ
  บางหน้าจากไฟล์อื่นไว้ตำแหน่งที่ต้องการ, และ**แยก**ช่วงหน้าเป็นไฟล์ใหม่
- **แปลง PDF เป็น Word (.docx) แบบตัวอักษรไม่เพี้ยน** — ใส่ฟอนต์/ขนาดช่อง
  complex-script และ `bidi` ให้ครบทุกจุด ซึ่งเป็นช่องที่ Word ใช้จริงกับภาษาไทย
  (ถ้าขาด เอกสาร TH SarabunPSK 16pt จะเปิดมาเป็น Calibri 11pt) พร้อมประกอบ
  สระ-วรรณยุกต์ที่ PDF แยกชิ้นมาให้กลับเป็นตัวเดียว เลือกได้ระหว่าง
  **คงหน้าตาเดิม** (วางทุกบรรทัดตามพิกัดจริง ตาราง/ฟอร์มไม่เลื่อน) กับ
  **พิมพ์แก้ต่อได้ง่าย** (ย่อหน้าปกติ + แปลงตารางมีเส้นเป็นตารางของ Word)
  หน้าที่อ่านตัวอักษรไม่ออกจะใส่เป็นรูปให้แทนและบอกเลขหน้า
- **บีบอัด PDF ลดขนาดไฟล์ ทีเดียวหลายไฟล์** — ลากไฟล์กี่ไฟล์ก็ได้มาวางในหน้าต่าง
  เดียว ตั้งค่าครั้งเดียว สั่งรวดเดียวจบ มีตารางบอกทีละไฟล์ว่าเหลือเท่าไร ลดกี่
  เปอร์เซ็นต์ เลือกได้ 3 ระดับ (คุณภาพสูง / สมดุล / เล็กที่สุด) เอกสารสแกนทั่วไป
  มักลดลง 60–80% เสริมด้วยการแปลงรูปเป็นขาวดำและตัดฟอนต์ที่ฝังมาให้เหลือเฉพาะ
  ตัวอักษรที่ใช้จริง **ไฟล์ต้นฉบับไม่ถูกแตะ** (ได้ไฟล์ใหม่ `ชื่อเดิม_compressed.pdf`)
  ไฟล์ผลลัพธ์ถูกเปิดตรวจก่อนรับเสมอ ถ้าเล็กลงไม่ได้จะคืนไฟล์เดิมให้ — และ
  **ทำในเครื่องล้วนๆ** เอกสารที่อัปโหลดขึ้นเว็บบีบอัด PDF ไม่ได้ ก็บีบตรงนี้ได้
- **ส่งออก** เป็น PDF, PNG, JPG หรือข้อความ; ใส่**รหัสผ่าน AES-256**
- ขยับข้อความ/รูปที่เลือก**ทีละ 1 จุดด้วยปุ่มลูกศร** (Shift = 5 จุด)
- **Undo/Redo** เต็มรูปแบบ และสลับ **ไทย/อังกฤษ** ด้วยปุ่มธงมุมขวาบน

### สิ่งที่ต้องมี
- Python 3.10 ขึ้นไป
- `pip install -r requirements.txt` (PyQt6, PyMuPDF)

### วิธีรัน
```bash
pip install -r requirements.txt
python main.py
```

### วิธีสร้างไฟล์ .exe (Windows)
ดูรายละเอียดในไฟล์ `BUILD.md` — โดยสรุปใช้ PyInstaller ตามคำสั่งด้านบน
ได้ไฟล์ `dist\WnyEditPDF.exe` ก๊อปไปเครื่องอื่นใช้ได้เลย

> Windows SmartScreen อาจเตือนว่า "ไม่รู้จักผู้เผยแพร่" เพราะไฟล์ไม่ได้เซ็น
> ดิจิทัล — ปลอดภัย กด **More info → Run anyway** ได้เลย

### หมายเหตุเรื่องลิขสิทธิ์
PyQt6 เป็น GPL และ PyMuPDF เป็น AGPL ใช้ภายในองค์กรได้ฟรี หากนำไปขายเชิงพาณิชย์
ต้องปฏิบัติตามเงื่อนไขสัญญาอนุญาต (เปิดซอร์ส หรือซื้อไลเซนส์เชิงพาณิชย์)

## License

Licensed under **AGPL-3.0** to comply with its dependencies (PyMuPDF is AGPL-3.0,
PyQt6 is GPL-3.0). See `LICENSE` and `THIRD_PARTY_LICENSES.md` for details.
