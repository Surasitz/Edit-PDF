# WnyEditPDF

A free, offline desktop **PDF reader & editor** with first-class Thai-language
support, built with Python + PyQt6 + PyMuPDF, with the open-source
[PdfCraft](https://github.com/storytold/pdfcraft) engine (Rust) built in for
whole-document tools. Everything runs locally on your machine — no internet,
no accounts, no limits, no data ever leaves your computer.

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
- **Digital signatures with a certificate** — sign with a .p12/.pfx digital ID
  or one in the Windows certificate store (smart cards and USB tokens too),
  PAdES SHA-256, with an optional Thai "digitally signed by" box and
  certification (no changes allowed). **Validate** the signatures in any file:
  was it changed after signing, and is the signer trusted? Create a personal
  digital ID in a few clicks.
- **Document menu** — properties (title, author, PDF version, embedded fonts,
  security), bookmarks editor, **compare two versions** (report PDF or the
  differences marked as comments), **PDF/A-2b** verify and convert for
  archiving, accessibility checker, **remove hidden information** before a
  file leaves your organisation, flatten comments/forms, and **automatic form
  field detection** that turns the blanks of a printed form into fillable
  fields. Thai values typed into form fields are drawn with a real Thai font.
- **Combine** PDFs, images and text files into one PDF with a bookmark per
  file; **split** every N pages, at bookmarks or by size; export the embedded
  images; **crop** pages; **print**; clear / export / import form data (XFDF,
  FDF, CSV, XML); turn web addresses into links.
- **Export** to PDF, PNG, JPG or plain text; **AES-256 password** protection
  with optional restrictions (no printing / copying / editing).
- **An Acrobat-style workspace**: mode tabs (All tools, Read, Edit, Convert,
  E-Sign), an All-tools panel with 86 tools in 14 colour-coded families, a
  floating tool rail beside the page, page thumbnails on the right, a
  distraction-free Read mode, and **Ctrl+K** to search every command in Thai
  or English. A welcome screen shows recent files and the popular tools.
- More tools from the PdfCraft catalogue: header and footer with page numbers,
  dates and **Bates numbering**, coloured-paper backgrounds, blank / clipboard
  documents, duplicate and replace pages, page labels (i ii / 1 2 3), underline
  / strike-out / squiggly markup, rectangles, ovals and lines, a comment list,
  **find-and-redact** across the whole file, redacting whole pages, adding form
  fields by hand, removing a password, and HTML export with intact Thai.
- Nudge the selected text/image by **1 pt with the arrow keys** (Shift = 5 pt).
- Full **Undo/Redo**, and a **Thai / English** UI you can switch with the flag
  button (top-right).

### Requirements
- Python 3.10+
- `pip install -r requirements.txt` (PyQt6, PyMuPDF)
- To build the engine: Rust (https://rustup.rs) + Visual Studio Build Tools (C++)

### Run
```bash
pip install -r requirements.txt
python main.py
```

### Build a standalone .exe (Windows)
```bat
build.bat
```
It builds the PdfCraft engine, then a single `dist/WnyEditPDF.exe` with the
engine, fonts and everything else inside — copy it to any machine. Without a
built engine the app still runs; only the engine-backed tools say it is
missing. (See `BUILD.md`.)

> Windows SmartScreen may warn that the publisher is unknown because the binary
> is not code-signed. It is safe — click **More info → Run anyway**.

### Project layout
```
WnyEditPDF/
├── main.py                 # entry point
├── requirements.txt
├── pyproject.toml          # package metadata
├── build.bat               # builds the engine + the single .exe
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
│   ├── engine.py           # bridge to the PdfCraft engine (pdfcraft-cli)
│   ├── doc_tools.py        # engine-backed tools, their dialogs, welcome screen, Ctrl+K
│   ├── catalog.py          # every tool, grouped as the tool panel shows them
│   ├── shell.py            # the All-tools panel
│   ├── icons.py            # tinted line icons (assets/icons: Lucide, ISC)
│   ├── widgets.py          # PageView, dialogs, thumbnail list, search bar
│   ├── window.py           # MainWindow — menus, toolbars, event wiring
│   ├── assets/             # logo.png / logo.ico
│   └── vendor/qrcode/      # bundled QR library (no external install needed)
└── fonts/                  # 59 bundled Thai .ttf fonts (TH Sarabun family, etc.)

../pdfcraft/                # PdfCraft engine source (Rust, MIT OR Apache-2.0)
└── WNYEDITPDF.md           # what it is, upstream commit, local changes
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
- **ลายเซ็นดิจิทัลด้วยใบรับรอง** — ลงนามด้วยไฟล์ .p12/.pfx หรือใบรับรองใน Windows
  (รวมบัตร/โทเคน USB) แบบ PAdES SHA-256 แสดงกรอบ "ลงนามดิจิทัลโดย…" เป็นภาษาไทยได้
  และล็อกเอกสารห้ามแก้หลังลงนามได้ — **ตรวจสอบลายเซ็น** ว่าไฟล์ถูกแก้หลังลงนามหรือไม่
  และสร้างใบรับรองส่วนตัวได้เอง
- **เมนูเอกสาร** — คุณสมบัติเอกสาร (ฟอนต์ที่ฝัง ความปลอดภัย), จัดการบุ๊กมาร์ก,
  **เปรียบเทียบ 2 เวอร์ชัน** (รายงาน PDF หรือใส่จุดต่างเป็นคอมเมนต์), ตรวจ/แปลง
  **PDF/A-2b** สำหรับเก็บถาวรในระบบสารบรรณอิเล็กทรอนิกส์, ตรวจการเข้าถึง,
  **ลบข้อมูลแฝง**ก่อนส่งไฟล์ออกนอกหน่วยงาน, Flatten และ**สร้างช่องกรอกฟอร์มอัตโนมัติ**
  จากเส้นใต้/กล่องในแบบฟอร์ม — กรอกภาษาไทยในช่องฟอร์มได้ตัวอักษรครบ
- **รวม**หลายไฟล์ (PDF + รูป + ข้อความ) เป็น PDF เดียวพร้อมบุ๊กมาร์ก, **แยก**ไฟล์ทุก N หน้า/
  ตามบุ๊กมาร์ก/ตามขนาด, ดึงรูปที่ฝังในไฟล์, **ครอบตัดหน้า**, **พิมพ์**, ล้าง/ส่งออก/นำเข้า
  ข้อมูลฟอร์ม, ทำ URL ในข้อความให้กดได้
- **ส่งออก** เป็น PDF, PNG, JPG หรือข้อความ; ใส่**รหัสผ่าน AES-256** และจำกัดสิทธิ์
  ห้ามพิมพ์/คัดลอก/แก้ไขได้
- **หน้าตาแบบ Acrobat**: แท็บ เครื่องมือทั้งหมด · อ่าน · แก้ไข · แปลงไฟล์ · ลงนาม,
  แผงเครื่องมือ 86 อย่างแบ่ง 14 หมวดสี, แถบเครื่องมือลอยข้างหน้ากระดาษ, ภาพย่อหน้าด้านขวา,
  โหมดอ่านเต็มจอ และกด **Ctrl+K** ค้นหาคำสั่งได้ทุกคำสั่ง หน้าแรกมีไฟล์ล่าสุดและเครื่องมือยอดนิยม
- **หัว/ท้ายกระดาษ** (เลขหน้า วันที่ พ.ศ.) และ**เลข Bates**, สีพื้นหลังแบบกระดาษสี,
  สร้างเอกสารเปล่า/จากคลิปบอร์ด, ทำซ้ำ/แทนที่หน้า, ป้ายเลขหน้า, ขีดเส้นใต้/ขีดฆ่า/เส้นหยัก,
  สี่เหลี่ยม/วงรี/เส้นตรง, รายการคอมเมนต์, **ค้นหาคำแล้วลบถาวรทุกจุด** (เช่น เลขบัตรประชาชน
  ตาม PDPA), ลบทั้งหน้า, เพิ่มช่องฟอร์มเอง, ปลดรหัสผ่าน และส่งออกเป็นเว็บเพจ
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
ดับเบิลคลิก `build.bat` (ต้องมี Python, Rust และ Visual Studio Build Tools) —
ได้ไฟล์ `dist\WnyEditPDF.exe` **ไฟล์เดียว** ที่มีเอนจินและฟอนต์อยู่ข้างใน
ก๊อปไปเครื่องอื่นใช้ได้เลย รายละเอียดใน `BUILD.md`

> Windows SmartScreen อาจเตือนว่า "ไม่รู้จักผู้เผยแพร่" เพราะไฟล์ไม่ได้เซ็น
> ดิจิทัล — ปลอดภัย กด **More info → Run anyway** ได้เลย

### หมายเหตุเรื่องลิขสิทธิ์
PyQt6 เป็น GPL และ PyMuPDF เป็น AGPL ใช้ภายในองค์กรได้ฟรี หากนำไปขายเชิงพาณิชย์
ต้องปฏิบัติตามเงื่อนไขสัญญาอนุญาต (เปิดซอร์ส หรือซื้อไลเซนส์เชิงพาณิชย์)

## License

Licensed under **AGPL-3.0** to comply with its dependencies (PyMuPDF is AGPL-3.0,
PyQt6 is GPL-3.0). The bundled PdfCraft engine is MIT OR Apache-2.0 (its
`LICENSE-*` and `NOTICE` files are in `../pdfcraft`). See `LICENSE` and
`THIRD_PARTY_LICENSES.md` for details.
