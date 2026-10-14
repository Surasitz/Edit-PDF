# สัญญาอนุญาตของไลบรารีที่ใช้ (Third-Party Licenses)

โปรแกรมนี้ใช้ไลบรารีของบุคคลที่สาม ซึ่งมีสัญญาอนุญาตดังนี้ — **สำคัญมากต่อการเผยแพร่**

| ไลบรารี | สัญญาอนุญาต | ผลต่อการเผยแพร่ |
|---------|-------------|------------------|
| [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) | GPL v3 หรือ Commercial | ถ้าใช้รุ่น GPL การแจกจ่ายโปรแกรมต้องเปิดซอร์สภายใต้ GPL v3 |
| [PyMuPDF](https://pymupdf.readthedocs.io/) | **AGPL v3** หรือ Commercial | AGPL เข้มกว่า GPL — ถ้าให้บริการผ่านเครือข่ายก็ต้องเปิดซอร์สด้วย |
| [qrcode](https://github.com/lincolnloop/python-qrcode) | BSD | ยืดหยุ่น ใช้ได้อิสระ (ฝังไว้ใน `wnyeditpdf/vendor/qrcode`) |
| [Lucide icons](https://lucide.dev) (ไอคอนใน `wnyeditpdf/assets/icons`) | ISC | ใช้ได้อิสระ ต้องเก็บ `LICENSE-lucide.txt` ไว้คู่กับไอคอน (มาพร้อม PdfCraft) |
| [PdfCraft](https://github.com/storytold/pdfcraft) (เอนจิน `pdfcraft-cli.exe`, ซอร์สใน `../pdfcraft`) | MIT หรือ Apache-2.0 | ใช้ร่วมกับ AGPL ได้ ต้องแนบ `LICENSE-MIT` / `LICENSE-APACHE` / `NOTICE` ของ PdfCraft ไปด้วย และแจ้งไฟล์ที่แก้ไข (ดู `../pdfcraft/WNYEDITPDF.md`) |

### เอนจิน PdfCraft

ไฟล์ `.exe` ฝัง `pdfcraft-cli.exe` ที่ build จากซอร์สในโฟลเดอร์ `../pdfcraft`
(storytold/pdfcraft commit `3146e87`, แก้ไขเพิ่มเติมตามที่ระบุใน `WNYEDITPDF.md`)
สัญญาอนุญาตและรายการไลบรารีที่เอนจินใช้ต่ออีกทอด (hayro, lopdf, ฟอนต์ Foxit
standard-14 แบบ BSD-3-Clause, CMap ของ Adobe แบบ BSD-3-Clause, ฟอนต์ Dancing Script
แบบ SIL OFL 1.1 ฯลฯ) อยู่ในไฟล์ `../pdfcraft/NOTICE`

ชื่อและโลโก้ ArtCraft เป็นเครื่องหมายการค้าของ ArtCraft Team ไม่ได้อยู่ในสัญญาอนุญาต
โอเพนซอร์ส — WnyEditPDF ไม่ใช้ชื่อหรือโลโก้ดังกล่าวในตัวโปรแกรม (อ้างถึงเพียง "PdfCraft engine"
เพื่อระบุที่มา)

## สรุปสำหรับผู้ที่จะเผยแพร่ต่อ

เนื่องจากโปรแกรมลิงก์กับ **PyMuPDF (AGPL v3)** และ **PyQt6 (GPL v3)** ตัวโปรแกรมรวม
(ไฟล์ .exe หรือซอร์สที่แจกจ่าย) จึงต้องอยู่ภายใต้เงื่อนไข copyleft ของ **AGPL v3**
เว้นแต่จะซื้อสัญญาอนุญาตเชิงพาณิชย์ (commercial license) ของ PyQt และ PyMuPDF

ดังนั้นไฟล์ `LICENSE` ของโปรเจกต์นี้จึงเลือกใช้ **AGPL v3** เพื่อให้สอดคล้องกับไลบรารีที่ใช้

หากต้องการเผยแพร่แบบปิดซอร์ส (proprietary) จะต้องจัดหาสัญญาอนุญาตเชิงพาณิชย์
ของทั้ง PyQt และ PyMuPDF ก่อน

## ฟอนต์ (Fonts)

ฟอนต์ในโฟลเดอร์ `fonts/` (เช่น TH Sarabun New, TH SarabunPSK, Sarabun) เป็นฟอนต์
สาธารณะที่แจกจ่ายได้ ผู้เผยแพร่ควรตรวจสอบเงื่อนไขการใช้งานของฟอนต์ลายเซ็นเฉพาะทาง
(เช่น B2_SIGN, SOV, KJR) ก่อนนำไปใช้เชิงพาณิชย์
