# การติดตั้งและสร้างไฟล์ปฏิบัติการ (Build Guide)

WnyEditPDF — โปรแกรมอ่าน/แก้ไข PDF ภาษาไทย

## 1. ติดตั้งไลบรารีที่ต้องใช้ (ครั้งแรกครั้งเดียว)

```bash
pip install -r requirements.txt
pip install pyinstaller        # เฉพาะตอนจะสร้างไฟล์ .exe
```

## 2. รันโปรแกรมจากซอร์ส (ไม่ต้อง build)

```bash
python main.py
```

## 3. สร้างไฟล์ .exe สำหรับแจกจ่าย

### Windows

```bat
pyinstaller --onefile --windowed --name WnyEditPDF ^
    --icon wnyeditpdf/assets/logo.ico ^
    --add-data "fonts;fonts" ^
    --add-data "wnyeditpdf/assets;wnyeditpdf/assets" ^
    --hidden-import qrcode ^
    --hidden-import fontTools ^
    main.py
```

### macOS / Linux

```bash
pyinstaller --onefile --windowed --name WnyEditPDF \
    --icon wnyeditpdf/assets/logo.ico \
    --add-data "fonts:fonts" \
    --add-data "wnyeditpdf/assets:wnyeditpdf/assets" \
    --hidden-import qrcode ^
    --hidden-import fontTools \
    main.py
```

ไฟล์ที่ได้จะอยู่ที่ `dist/WnyEditPDF.exe` (Windows) — คัดลอกไปเครื่องอื่นได้เลย

## หมายเหตุ

- โฟลเดอร์ `fonts/` (ฟอนต์ไทย 59 ไฟล์) และ `wnyeditpdf/assets/logo.png` ต้องอยู่ครบตอน build
- ไลบรารี `qrcode` ถูกฝังไว้ใน `wnyeditpdf/vendor/qrcode` แล้ว จึงใช้งาน QR ได้แม้ไม่ได้ `pip install qrcode` (แต่ยังใส่ `--hidden-import qrcode ^
    --hidden-import fontTools` ไว้เผื่อกรณีมีติดตั้งในระบบ)
