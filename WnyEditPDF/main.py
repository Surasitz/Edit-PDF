#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WnyEditPDF — จุดเริ่มต้นโปรแกรม (entry point)

โครงสร้างโค้ดอยู่ในแพ็กเกจ wnyeditpdf/ (แยกเป็นคลาสตามหน้าที่):
  wnyeditpdf/config.py    ค่าคงที่ ธีมสี โหมดเครื่องมือ
  wnyeditpdf/fonts.py     FontManager  — จัดการฟอนต์
  wnyeditpdf/document.py  PdfDocument  — อ่าน/แก้ไข PDF + Undo/Redo
  wnyeditpdf/widgets.py   PageView, กล่องลายเซ็น, กล่องข้อความ ฯลฯ
  wnyeditpdf/window.py    MainWindow   — หน้าต่างหลักและการเชื่อมทุกส่วนเข้าด้วยกัน
  wnyeditpdf/i18n.py      คำแปลไทย/อังกฤษ
  wnyeditpdf/assets/      ไอคอน/โลโก้
  wnyeditpdf/vendor/      ไลบรารีที่ฝังมา (qrcode)
"""

from wnyeditpdf.window import run

if __name__ == "__main__":
    run()
