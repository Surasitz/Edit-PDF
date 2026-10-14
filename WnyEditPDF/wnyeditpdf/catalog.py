# -*- coding: utf-8 -*-
"""The tool catalogue: every tool in the app, grouped the way the tool panel
shows them (the "All tools" layout PdfCraft and Acrobat use), as data.

The tool panel, the mode tabs and the welcome screen are built from this
table, so a tool is added in one place. Each item names the MainWindow method
it runs; ``needs_doc`` items first ask for a file when none is open.
"""

from .config import (MODE_ADD_TEXT, MODE_DELETE_TEXT, MODE_EDIT_TEXT, MODE_LINK,
                     MODE_MOVE_TEXT, MODE_PEN, MODE_WHITEOUT)

RED = "#e03e3e"
PURPLE = "#8e4ee6"
BLUE = "#3a6fe8"
GREEN = "#2d9d5b"
ORANGE = "#e88a1a"
TEAL = "#149ca8"
PINK = "#d63b8f"


class Item:
    __slots__ = ("label", "icon", "method", "args", "needs_doc")

    def __init__(self, label, icon, method, *args, needs_doc=True):
        self.label, self.icon, self.method, self.args = label, icon, method, args
        self.needs_doc = needs_doc

    def run(self, win):
        getattr(win, self.method)(*self.args)


class Group:
    __slots__ = ("id", "label", "icon", "hue", "desc", "sections")

    def __init__(self, gid, label, icon, hue, desc, sections):
        self.id, self.label, self.icon, self.hue = gid, label, icon, hue
        self.desc, self.sections = desc, sections


def mode(label, icon, md):
    return Item(label, icon, "change_mode", md)


GROUPS = [
    Group("export", "ส่งออก / แปลงไฟล์", "file-output", BLUE, "Word, เว็บเพจ, รูปภาพ, ข้อความ", [
        ("ส่งออกเป็น", [
            Item("Word (.docx) ภาษาไทยไม่เพี้ยน", "file-text", "export_word"),
            Item("เว็บเพจ (HTML)", "code-xml", "export_html"),
            Item("รูปภาพ PNG (หน้านี้)", "image", "export_png"),
            Item("ดึงรูปที่ฝังอยู่ในไฟล์", "image-plus", "export_embedded_images"),
            Item("ข้อความล้วน (.txt)", "type", "export_text"),
        ]),
    ]),
    Group("create", "สร้าง PDF", "file-plus", RED, "เอกสารเปล่า, รูปภาพ, คลิปบอร์ด", [
        ("สร้างจาก", [
            Item("เอกสารเปล่า", "file-plus-2", "create_blank", needs_doc=False),
            Item("หลายไฟล์ / รูปภาพ", "files", "combine_files", needs_doc=False),
            Item("ภาพในคลิปบอร์ด", "clipboard-paste", "create_from_clipboard", needs_doc=False),
        ]),
    ]),
    Group("combine", "รวมไฟล์", "files", PURPLE, "รวมหลายไฟล์เป็น PDF เดียว", [
        ("รวม", [
            Item("รวมหลายไฟล์เป็น PDF ใหม่", "files", "combine_files", needs_doc=False),
            Item("แทรกหน้าจากไฟล์อื่น", "file-input", "merge_pdf"),
        ]),
    ]),
    Group("organize", "จัดการหน้า", "layout-grid", GREEN, "หมุน ลบ แทรก ทำซ้ำ แยก ครอบตัด", [
        ("หน้า", [
            Item("หมุนตามเข็ม", "rotate-cw", "rotate_page", 90),
            Item("หมุนทวนเข็ม", "rotate-ccw", "rotate_page", -90),
            Item("ลบหน้านี้", "trash-2", "delete_page"),
            Item("แทรกหน้าว่าง", "file-plus", "insert_blank_page"),
            Item("ทำซ้ำหน้านี้", "copy-plus", "duplicate_page"),
            Item("แทนที่หน้าด้วยไฟล์อื่น", "replace", "replace_pages"),
            Item("เลื่อนหน้าขึ้น", "chevron-up", "move_page", -1),
            Item("เลื่อนหน้าลง", "chevron-down", "move_page", 1),
        ]),
        ("แยกและตัด", [
            Item("แยกช่วงหน้าเป็นไฟล์ใหม่", "file-output", "extract_pages"),
            Item("แยกเป็นหลายไฟล์", "scissors", "split_document"),
            Item("ครอบตัดหน้า", "crop", "crop_pages"),
            Item("ป้ายเลขหน้า (1 2 3 / i ii / A B)", "list-ordered", "page_labels_ui"),
        ]),
    ]),
    Group("edit", "แก้ไข PDF", "file-pen-line", PINK, "แก้ข้อความ รูป หัวกระดาษ ลายน้ำ", [
        ("ข้อความและรูป", [
            mode("แก้ข้อความเดิม", "pencil", MODE_EDIT_TEXT),
            mode("เพิ่มข้อความ", "type", MODE_ADD_TEXT),
            mode("ขยับ / ย่อขยาย", "move", MODE_MOVE_TEXT),
            mode("ลบข้อความ / รูป", "trash", MODE_DELETE_TEXT),
            Item("แทรกรูปภาพ", "image-plus", "tool_image"),
            Item("ค้นหา / แทนที่", "file-search", "search_text"),
            Item("ปรับรูปสแกน (สว่าง / คม / เอียง)", "contrast", "tool_enhance_scan"),
        ]),
        ("ใส่ทุกหน้า", [
            Item("หัวกระดาษ / ท้ายกระดาษ", "heading", "header_footer_ui"),
            Item("เลขหน้า", "hash", "add_page_numbers_ui"),
            Item("เลข Bates (เอกสารคดี)", "tag", "header_footer_ui", True),
            Item("ลายน้ำ", "droplet", "add_watermark"),
            Item("สีพื้นหลัง", "paint-bucket", "add_background"),
        ]),
        ("ลิงก์", [
            mode("ลากคลุมเพื่อใส่ลิงก์", "link", MODE_LINK),
            Item("ลิงก์บนข้อความ", "link-2", "tool_link_on_text"),
            Item("ทำ URL ให้กดได้อัตโนมัติ", "globe", "auto_links"),
            Item("สร้าง QR Code", "scan", "tool_qr"),
        ]),
    ]),
    Group("comment", "คอมเมนต์", "message-square", ORANGE, "ไฮไลท์ ขีดเส้นใต้ โน้ต รูปทรง", [
        ("มาร์กข้อความ", [
            Item("ไฮไลท์", "highlighter", "set_markup", "highlight"),
            Item("ขีดเส้นใต้", "underline", "set_markup", "underline"),
            Item("ขีดฆ่า", "strikethrough", "set_markup", "strikeout"),
            Item("เส้นหยัก", "spline", "set_markup", "squiggly"),
        ]),
        ("โน้ตและรูปทรง", [
            Item("โน้ต", "sticky-note", "_set_comment_kind", "note"),
            Item("กล่องข้อความ", "message-square-text", "_set_comment_kind", "textbox"),
            Item("ลูกศรชี้", "arrow-up-right", "_set_comment_kind", "arrow"),
            mode("ปากกาวาดอิสระ", "pen-tool", MODE_PEN),
            Item("สี่เหลี่ยม", "square", "_set_comment_kind", "rect"),
            Item("วงรี", "circle", "_set_comment_kind", "oval"),
            Item("เส้นตรง", "minus", "_set_comment_kind", "line"),
        ]),
        ("ตรวจทาน", [
            Item("รายการคอมเมนต์ทั้งหมด", "messages-square", "comment_list"),
            Item("ฝังคอมเมนต์ลงหน้า (Flatten)", "layers", "flatten_document"),
        ]),
    ]),
    Group("fill_sign", "กรอกและลงชื่อ", "pen-line", PURPLE, "ข้อความ เครื่องหมาย ตราประทับ ลายเซ็น", [
        ("กรอก", [
            mode("พิมพ์ข้อความ", "type", MODE_ADD_TEXT),
            Item("เครื่องหมายถูก", "check", "tool_symbol", "check"),
            Item("กากบาท", "x", "tool_symbol", "cross"),
            Item("จุด", "circle-dot", "tool_symbol", "dot"),
            Item("วงกลมล้อมรอบ", "circle", "tool_symbol", "circle"),
            Item("ขีดเส้น / ขีดฆ่า", "minus", "tool_symbol", "dash"),
            Item("ตราประทับ (สำเนาถูกต้อง / วันที่)", "stamp", "tool_stamp"),
        ]),
        ("ลงชื่อ", [
            Item("ลายเซ็นของฉัน (วาด / รูป / พิมพ์)", "signature", "tool_signature"),
        ]),
    ]),
    Group("certificate", "ลายเซ็นดิจิทัล", "badge-check", TEAL, "ลงนามและตรวจสอบด้วยใบรับรอง", [
        ("ใบรับรอง", [
            Item("ลงนามด้วยใบรับรอง", "signature", "sign_digital"),
            Item("ตรวจสอบลายเซ็นในไฟล์", "shield-check", "verify_signatures"),
            Item("สร้างใบรับรองส่วนตัว (.p12)", "file-lock-2", "create_digital_id", needs_doc=False),
        ]),
    ]),
    Group("form", "แบบฟอร์ม", "text-cursor-input", PURPLE, "กรอก สร้างช่อง ส่งออกข้อมูล", [
        ("กรอก", [
            Item("กรอกฟอร์ม (เลือกจากรายการช่อง)", "list-checks", "fill_form_dialog"),
            Item("ล้างค่าในฟอร์มทั้งหมด", "eraser", "form_reset_all"),
        ]),
        ("สร้างช่อง", [
            Item("หาช่องกรอกอัตโนมัติ", "wand-sparkles", "detect_form_fields"),
            Item("ช่องข้อความ", "text-cursor-input", "set_form_kind", "text"),
            Item("ช่องติ๊ก", "check-circle-2", "set_form_kind", "checkbox"),
            Item("รายการให้เลือก", "list", "set_form_kind", "combobox"),
            Item("ช่องลงลายเซ็น", "pen-line", "set_form_kind", "signature"),
        ]),
        ("ข้อมูล", [
            Item("ส่งออกข้อมูลฟอร์ม / คอมเมนต์", "file-down", "form_export_data"),
            Item("นำเข้าข้อมูลฟอร์ม / คอมเมนต์", "file-input", "form_import_data"),
            Item("ฝังช่องฟอร์มลงหน้า (Flatten)", "layers", "flatten_document"),
        ]),
    ]),
    Group("protect", "ป้องกันไฟล์", "lock", BLUE, "รหัสผ่าน จำกัดสิทธิ์ ลบข้อมูลแฝง", [
        ("ป้องกัน", [
            Item("ล็อกรหัสผ่าน / จำกัดสิทธิ์", "lock", "protect_document"),
            Item("ปลดรหัสผ่าน (บันทึกแบบไม่ล็อก)", "lock-open", "remove_security"),
            Item("ลบข้อมูลแฝง", "shield-check", "sanitize_document"),
        ]),
    ]),
    Group("redact", "ลบข้อมูลถาวร", "eraser", RED, "ค้นหาแล้วลบ ลากคลุม ลบทั้งหน้า", [
        ("ลบถาวร (Redact)", [
            mode("ลากคลุมพื้นที่ที่จะลบ", "square-dashed", MODE_WHITEOUT),
            Item("ค้นหาคำแล้วลบทุกจุด", "file-search", "find_and_redact"),
            Item("ลบทั้งหน้า", "file-x", "redact_pages_ui"),
            Item("ลบข้อมูลแฝง", "brush-cleaning", "sanitize_document"),
        ]),
    ]),
    Group("compress", "บีบอัด PDF", "gauge", RED, "ลดขนาดไฟล์ทีละหลายไฟล์", [
        ("ลดขนาด", [
            Item("บีบอัด PDF (ทีเดียวหลายไฟล์)", "gauge", "compress_pdfs", needs_doc=False),
        ]),
    ]),
    Group("compare", "เปรียบเทียบไฟล์", "git-compare", BLUE, "หาจุดต่างของสองเวอร์ชัน", [
        ("เปรียบเทียบ", [
            Item("เปรียบเทียบกับไฟล์เวอร์ชันอื่น", "git-compare", "compare_versions"),
        ]),
    ]),
    Group("standards", "มาตรฐานและข้อมูลเอกสาร", "file-check", GREEN, "PDF/A การเข้าถึง คุณสมบัติ บุ๊กมาร์ก", [
        ("มาตรฐาน", [
            Item("ตรวจ / แปลงเป็น PDF/A", "file-check", "pdfa_check"),
            Item("ตรวจการเข้าถึง (Accessibility)", "accessibility", "accessibility_check"),
        ]),
        ("ข้อมูลเอกสาร", [
            Item("คุณสมบัติเอกสาร", "info", "doc_properties"),
            Item("บุ๊กมาร์ก", "bookmark", "edit_bookmarks"),
            Item("ประวัติเวอร์ชัน (กู้ไฟล์เก่า)", "clock", "show_version_history"),
        ]),
    ]),
]

BY_ID = {g.id: g for g in GROUPS}

# the mode tabs across the top: which groups each one opens in the tool panel
TABS = [
    ("all", "เครื่องมือทั้งหมด", None),
    ("read", "อ่าน", None),
    ("edit", "แก้ไข", ["edit", "organize"]),
    ("convert", "แปลงไฟล์", ["export", "create"]),
    ("sign", "ลงนาม", ["fill_sign", "certificate"]),
]


def icons_used():
    names = set()
    for g in GROUPS:
        names.add(g.icon)
        for _title, items in g.sections:
            names.update(i.icon for i in items)
    return names
