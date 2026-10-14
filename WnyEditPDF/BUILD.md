# การติดตั้งและสร้างไฟล์ปฏิบัติการ (Build Guide)

WnyEditPDF ประกอบด้วย 2 ส่วนในโปรเจกต์เดียว:

| โฟลเดอร์ | ภาษา | หน้าที่ |
|---|---|---|
| `WnyEditPDF/` (โฟลเดอร์นี้) | Python + PyQt6 + PyMuPDF | ตัวโปรแกรม หน้าจอ และงานบนหน้ากระดาษทั้งหมด |
| `../pdfcraft/` | Rust | เอนจิน `pdfcraft-cli.exe` สำหรับงานระดับเอกสาร (ลายเซ็นดิจิทัล, PDF/A, เปรียบเทียบ ฯลฯ) |

ผลลัพธ์สุดท้ายคือ **`dist\WnyEditPDF.exe` ไฟล์เดียว** ที่ฝังเอนจิน ฟอนต์ และทุกอย่างไว้ข้างใน

## 1. สิ่งที่ต้องติดตั้ง (ครั้งแรกครั้งเดียว)

- Python 3.10 ขึ้นไป
- Rust (https://rustup.rs) และ Visual Studio Build Tools (เลือก "Desktop development with C++")

## 2. สร้างไฟล์ .exe (Windows)

```bat
build.bat
```

สคริปต์จะทำ 4 ขั้น: build เอนจิน Rust → ติดตั้งไลบรารี Python → สร้าง .exe ด้วย
PyInstaller (ฝัง `pdfcraft-cli.exe` ไว้ในโฟลเดอร์ `engine/` ภายใน) → ตรวจผลลัพธ์

ไฟล์ที่ได้คือ `dist\WnyEditPDF.exe` — คัดลอกไปเครื่องอื่นใช้ได้เลย ไม่ต้องติดตั้งอะไรเพิ่ม

## 3. รันจากซอร์ส (ไม่ต้องสร้าง .exe)

```bash
pip install -r requirements.txt
cd ../pdfcraft && cargo build --release -p pdfcraft-cli && cd ../WnyEditPDF
python main.py
```

โปรแกรมหาเอนจินที่ `../pdfcraft/target/release/pdfcraft-cli.exe` เอง
(หรือกำหนดเองด้วยตัวแปร `WNYEDITPDF_ENGINE`) ถ้าไม่มีเอนจิน โปรแกรมยังใช้งานได้ปกติ
เฉพาะเมนูในกลุ่ม "เอกสาร" และลายเซ็นดิจิทัลจะแจ้งว่าไม่พบเอนจิน

## 4. ทดสอบ

```bash
python -m pytest -q                                  # โปรแกรม (ทดสอบเอนจินด้วยถ้า build แล้ว)
cd ../pdfcraft && cargo test -p pdfcraft-redact      # ตัวอย่าง: ทดสอบ crate ของเอนจิน
```

## หมายเหตุ

- โฟลเดอร์ `fonts/` (ฟอนต์ไทย) และ `wnyeditpdf/assets/` ต้องอยู่ครบตอน build
- ไลบรารี `qrcode` ถูกฝังไว้ใน `wnyeditpdf/vendor/qrcode` แล้ว
- Windows SmartScreen อาจเตือนเพราะไฟล์ไม่ได้เซ็นดิจิทัล กด **More info → Run anyway**
