import io
import re
from typing import List, Dict, Tuple, Optional
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from database import DAYS_OF_WEEK, SLOTS, clean_order_number

DAY_MAPPING = {
    "السبت": "السبت",
    "سبت": "السبت",
    "saturday": "السبت",
    "sat": "السبت",

    "الاحد": "الأحد",
    "الأحد": "الأحد",
    "احد": "الأحد",
    "أحد": "الأحد",
    "sunday": "الأحد",
    "sun": "الأحد",

    "الاثنين": "الاثنين",
    "الإثنين": "الاثنين",
    "اثنين": "الاثنين",
    "إثنين": "الاثنين",
    "monday": "الاثنين",
    "mon": "الاثنين",

    "الثلاثاء": "الثلاثاء",
    "الثلاثا": "الثلاثاء",
    "ثلاثاء": "الثلاثاء",
    "ثلاثا": "الثلاثاء",
    "tuesday": "الثلاثاء",
    "tue": "الثلاثاء",

    "الاربعاء": "الأربعاء",
    "الأربعاء": "الأربعاء",
    "اربعاء": "الأربعاء",
    "أربعاء": "الأربعاء",
    "wednesday": "الأربعاء",
    "wed": "الأربعاء",

    "الخميس": "الخميس",
    "خميس": "الخميس",
    "thursday": "الخميس",
    "thu": "الخميس",
}

def normalize_day(day_str: any) -> Optional[str]:
    if day_str is None:
        return None
    cleaned = str(day_str).strip().lower()
    return DAY_MAPPING.get(cleaned)

def generate_template() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "نموذج إضافة الطلبات"
    ws.views.sheetView[0].rightToLeft = True

    # Styling
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Arial", size=10)
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    headers = ["رقم الطلب", "اليوم", "رقم الرف (0-9)", "ملاحظات"]
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center
        cell.border = thin_border

    sample_rows = [
        ["104921", "السبت", 0, "شحنة بغداد"],
        ["104922", "السبت", 1, "راجع زبون"],
        ["205813", "الأحد", 3, "إعادة توصيل"],
        ["309874", "الاثنين", 4, ""],
        ["410295", "الثلاثاء", 5, "مؤجل"],
        ["519286", "الأربعاء", 6, ""],
        ["628377", "الخميس", 9, "طلب مميز"]
    ]

    for row_idx, row_data in enumerate(sample_rows, 2):
        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = data_font
            cell.alignment = align_center if col_idx != 4 else align_right
            cell.border = thin_border

    # Instructions row at the bottom
    inst_row = len(sample_rows) + 4
    ws.cell(row=inst_row, column=1, value="* ملاحظات هامة:").font = Font(name="Arial", size=10, bold=True, color="B91C1C")
    instructions = [
        "1. الأيام المعتمدة هي: السبت، الأحد، الاثنين، الثلاثاء، الأربعاء، الخميس (الجمعة غير مشمول).",
        "2. رقم الرف يجب أن يكون رقماً صحيحاً من 0 إلى 9.",
        "3. رقم الطلب يجب أن يتكون من أرقام أو حروف إنجليزية.",
        "4. يمكنك أيضاً رفع ملف يحتوي فقط على عمود 'رقم الطلب' واختيار اليوم والرف من واجهة النظام مباشرة."
    ]
    for i, inst in enumerate(instructions):
        ws.cell(row=inst_row + i + 1, column=1, value=inst).font = Font(name="Arial", size=9, color="475569")

    # Column widths
    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 18
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 30

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()

def parse_excel_file(
    file_bytes: bytes, 
    default_day: Optional[str] = None, 
    default_slot: Optional[int] = None,
    auto_distribute_by_digit: bool = False
) -> Tuple[List[Dict], List[str]]:
    """
    Parses uploaded Excel workbook and extracts valid order dicts.
    Returns: (list_of_orders, list_of_warnings_or_errors)
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], ["الملف فارغ ولا يحتوي على أي بيانات"]

    # Identify header row (check first 5 rows)
    header_row_idx = -1
    col_order = -1
    col_day = -1
    col_slot = -1
    col_notes = -1

    for idx, row in enumerate(rows[:5]):
        if not row:
            continue
        for col_i, cell in enumerate(row):
            if cell is None:
                continue
            txt = str(cell).strip().lower()
            if any(k in txt for k in ["رقم الطلب", "الطلب", "شحنة", "order", "barcode", "باركود"]):
                if col_order == -1:
                    col_order = col_i
            elif any(k in txt for k in ["اليوم", "يوم", "day"]):
                if col_day == -1:
                    col_day = col_i
            elif any(k in txt for k in ["الرف", "رف", "رقم الرف", "slot", "shelf", "خانة"]):
                if col_slot == -1:
                    col_slot = col_i
            elif any(k in txt for k in ["ملاحظ", "تفاصيل", "notes", "note"]):
                if col_notes == -1:
                    col_notes = col_i

        if col_order != -1:
            header_row_idx = idx
            break

    # If no header found, assume column 0 is order number
    start_row = 1 if header_row_idx != -1 else 0
    if col_order == -1:
        col_order = 0

    orders_to_add = []
    warnings = []

    for r_idx in range(start_row, len(rows)):
        row = rows[r_idx]
        if not row or all(v is None for v in row):
            continue

        raw_order = row[col_order] if col_order < len(row) else None
        order_num = clean_order_number(raw_order)
        if not order_num:
            continue

        # Day resolution
        day = None
        if col_day != -1 and col_day < len(row) and row[col_day] is not None:
            day = normalize_day(row[col_day])
            if not day:
                raw_day_txt = str(row[col_day]).strip()
                if "جمع" in raw_day_txt or "fri" in raw_day_txt.lower():
                    warnings.append(f"السطر {r_idx+1}: يوم الجمعة عطلة وغير مشمول بالرفوف للطلب {order_num}")
                    continue
                else:
                    warnings.append(f"السطر {r_idx+1}: اليوم '{raw_day_txt}' غير معروف")
        
        if not day and default_day:
            day = normalize_day(default_day)

        if not day:
            warnings.append(f"السطر {r_idx+1}: لم يتم تحديد اليوم للطلب {order_num}")
            continue

        # Slot resolution
        slot = None
        if col_slot != -1 and col_slot < len(row) and row[col_slot] is not None:
            raw_slot_val = row[col_slot]
            try:
                # Could be float in excel e.g. 3.0
                s_int = int(float(str(raw_slot_val).strip()))
                if s_int in SLOTS:
                    slot = s_int
                else:
                    warnings.append(f"السطر {r_idx+1}: الرف {s_int} خارج النطاق (0-9)")
            except Exception:
                pass

        if slot is None:
            if auto_distribute_by_digit:
                # Find last digit in order number
                digits = re.findall(r'\d', order_num)
                if digits:
                    slot = int(digits[-1])
                else:
                    slot = 0
            elif default_slot is not None:
                try:
                    slot = int(default_slot)
                except Exception:
                    slot = None

        if slot is None or slot not in SLOTS:
            warnings.append(f"السطر {r_idx+1}: لم يتم تحديد رقم الرف (0-9) للطلب {order_num}")
            continue

        # Notes
        notes = ""
        if col_notes != -1 and col_notes < len(row) and row[col_notes] is not None:
            notes = str(row[col_notes]).strip()

        orders_to_add.append({
            "order_number": order_num,
            "day": day,
            "slot": slot,
            "notes": notes
        })

    return orders_to_add, warnings

def export_orders_to_excel(orders: List[Dict], sheet_title: str = "الطلبات") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]
    ws.views.sheetView[0].rightToLeft = True

    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Arial", size=10)
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0')
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    headers = ["ت", "رقم الطلب", "اليوم", "رقم الرف", "الحالة", "الملاحظات", "تاريخ الإضافة"]
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center
        cell.border = thin_border

    for row_idx, order in enumerate(orders, 2):
        row_vals = [
            row_idx - 1,
            order.get("order_number", ""),
            order.get("day", ""),
            f"الرف {order.get('slot', 0)}",
            order.get("status", "في الرف"),
            order.get("notes", ""),
            order.get("created_at", "")
        ]
        for col_idx, val in enumerate(row_vals, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = data_font
            cell.alignment = align_right if col_idx == 6 else align_center
            cell.border = thin_border

    # Format widths
    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 22
    ws.column_dimensions['C'].width = 16
    ws.column_dimensions['D'].width = 14
    ws.column_dimensions['E'].width = 14
    ws.column_dimensions['F'].width = 30
    ws.column_dimensions['G'].width = 22

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()
