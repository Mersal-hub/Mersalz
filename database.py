import sqlite3
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "shelves.db")

DAYS_OF_WEEK = ["السبت", "الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس"]
SLOTS = list(range(10)) # 0 to 9

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Password hashing with SHA-256 + salt
def hash_password(password: str, salt: Optional[str] = None) -> str:
    if not salt:
        salt = secrets.token_hex(8)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${h}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, h = stored_hash.split("$", 1)
        test_h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return test_h == h
    except Exception:
        return False

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Orders table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT NOT NULL UNIQUE,
            day TEXT NOT NULL,
            slot INTEGER NOT NULL,
            notes TEXT DEFAULT '',
            status TEXT DEFAULT 'في الرف',
            created_by TEXT DEFAULT 'admin',
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_day_slot ON orders(day, slot)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_num ON orders(order_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_slot ON orders(slot)")

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'employee', -- 'admin' or 'employee'
            can_add INTEGER NOT NULL DEFAULT 1,
            can_delete INTEGER NOT NULL DEFAULT 0,
            can_edit INTEGER NOT NULL DEFAULT 0,
            can_export INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    # Sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Activity log table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    # Seed Admin User if not exists
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    admin_row = cursor.fetchone()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not admin_row:
        admin_pass_hash = hash_password("admin123")
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, can_add, can_delete, can_edit, can_export, is_active, created_at)
            VALUES ('admin', ?, 'مدير النظام (ZMC Admin)', 'admin', 1, 1, 1, 1, 1, ?)
        """, (admin_pass_hash, now_str))

    # Seed default sample employee if not exists
    cursor.execute("SELECT id FROM users WHERE username = 'worker1'")
    if not cursor.fetchone():
        worker_hash = hash_password("123456")
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, can_add, can_delete, can_edit, can_export, is_active, created_at)
            VALUES ('worker1', ?, 'موظف المستودع', 'employee', 1, 0, 1, 0, 1, ?)
        """, (worker_hash, now_str))

    conn.commit()
    conn.close()

# --- User & Session Operations ---

def authenticate_user(username: str, password: str) -> Optional[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
    user = cursor.fetchone()
    conn.close()
    if not user:
        return None
    user_dict = dict(user)
    if not user_dict.get("is_active", 1):
        return None
    if verify_password(password, user_dict["password_hash"]):
        # Do not leak hash
        del user_dict["password_hash"]
        return user_dict
    return None

def create_session(user_id: int, days_valid: int = 7) -> str:
    token = secrets.token_hex(32)
    now = datetime.now()
    expires = now + timedelta(days=days_valid)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sessions (token, user_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
    """, (token, user_id, now.strftime("%Y-%m-%d %H:%M:%S"), expires.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    return token

def get_user_by_session(token: str) -> Optional[Dict]:
    if not token:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.username, u.full_name, u.role, u.can_add, u.can_delete, u.can_edit, u.can_export, u.is_active, s.expires_at
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ?
    """, (token,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    
    user_data = dict(row)
    if not user_data.get("is_active", 1):
        return None
        
    # Check expiration
    try:
        exp = datetime.strptime(user_data["expires_at"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() > exp:
            delete_session(token)
            return None
    except Exception:
        pass
        
    return user_data

def delete_session(token: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_all_users() -> List[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, full_name, role, can_add, can_delete, can_edit, can_export, is_active, created_at 
        FROM users ORDER BY role ASC, id ASC
    """)
    users = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return users

def get_user_by_id(user_id: int) -> Optional[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, full_name, role, can_add, can_delete, can_edit, can_export, is_active, created_at FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(
    username: str, 
    password: str, 
    full_name: str, 
    role: str = "employee", 
    can_add: int = 1, 
    can_delete: int = 0, 
    can_edit: int = 0, 
    can_export: int = 0
) -> Tuple[bool, str, Optional[Dict]]:
    uname = username.strip().lower()
    if not uname or len(uname) < 3:
        return False, "اسم المستخدم يجب أن يكون 3 أحرف على الأقل", None
    if not password or len(password) < 4:
        return False, "كلمة المرور يجب أن تكون 4 أحرف أو أرقام على الأقل", None
    if not full_name.strip():
        return False, "يرجى كتابة الاسم الكامل للموظف", None

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE username = ?", (uname,))
        if cursor.fetchone():
            conn.close()
            return False, f"اسم المستخدم '{uname}' مستخدم بالفعل، اختر اسماً آخر", None

        p_hash = hash_password(password)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, can_add, can_delete, can_edit, can_export, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (uname, p_hash, full_name.strip(), role, can_add, can_delete, can_edit, can_export, now_str))
        conn.commit()
        new_id = cursor.lastrowid
        cursor.execute("SELECT id, username, full_name, role, can_add, can_delete, can_edit, can_export, is_active, created_at FROM users WHERE id = ?", (new_id,))
        created = dict(cursor.fetchone())
        conn.close()
        return True, "تم إنشاء حساب الموظف وتحديد الصلاحيات بنجاح", created
    except Exception as e:
        conn.close()
        return False, f"حدث خطأ أثناء إنشاء المستخدم: {str(e)}", None

def update_user(
    user_id: int, 
    full_name: Optional[str] = None, 
    password: Optional[str] = None,
    role: Optional[str] = None,
    can_add: Optional[int] = None,
    can_delete: Optional[int] = None,
    can_edit: Optional[int] = None,
    can_export: Optional[int] = None,
    is_active: Optional[int] = None
) -> Tuple[bool, str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    existing = cursor.fetchone()
    if not existing:
        conn.close()
        return False, "المستخدم غير موجود"

    updates = []
    params = []
    if full_name is not None and full_name.strip():
        updates.append("full_name = ?")
        params.append(full_name.strip())
    if password is not None and len(password.strip()) >= 4:
        updates.append("password_hash = ?")
        params.append(hash_password(password.strip()))
    if role is not None and role in ("admin", "employee"):
        updates.append("role = ?")
        params.append(role)
    if can_add is not None:
        updates.append("can_add = ?")
        params.append(int(can_add))
    if can_delete is not None:
        updates.append("can_delete = ?")
        params.append(int(can_delete))
    if can_edit is not None:
        updates.append("can_edit = ?")
        params.append(int(can_edit))
    if can_export is not None:
        updates.append("can_export = ?")
        params.append(int(can_export))
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(int(is_active))

    if not updates:
        conn.close()
        return True, "لم يتم إجراء أي تعديلات"

    params.append(user_id)
    cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return True, "تم تحديث بيانات الموظف وصلاحياته بنجاح"

def delete_user(user_id: int) -> Tuple[bool, str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, role FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "المستخدم غير موجود"
    if row["username"] == "admin":
        conn.close()
        return False, "لا يمكن حذف حساب المدير الرئيسي"
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True, f"تم حذف حساب الموظف {row['username']} بنجاح"

def log_activity(username: str, action: str, details: str = ""):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO activity_logs (username, action, details, created_at)
            VALUES (?, ?, ?, ?)
        """, (username, action, details, now_str))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_activity_logs(limit: int = 40) -> List[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM activity_logs ORDER BY id DESC LIMIT ?", (limit,))
    logs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return logs

# --- Orders Operations ---

def clean_order_number(raw: any) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    if text.endswith(".0"):
        text = text[:-2]
    cleaned = "".join(c for c in text if c.isalnum() or c in "-_")
    return cleaned

def add_order(order_number: str, day: str, slot: int, notes: str = "", username: str = "admin") -> Tuple[bool, str, Optional[Dict]]:
    order_num = clean_order_number(order_number)
    if not order_num:
        return False, "رقم الطلب فارغ أو غير صالح", None
    
    if day not in DAYS_OF_WEEK:
        return False, f"اليوم '{day}' غير صحيح. الأيام المتاحة: {', '.join(DAYS_OF_WEEK)} (عدا الجمعة)", None
        
    try:
        slot = int(slot)
        if slot not in SLOTS:
            return False, f"رقم الرف يجب أن يكون من 0 إلى 9", None
    except (ValueError, TypeError):
        return False, "رقم الرف غير صالح", None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM orders WHERE order_number = ?", (order_num,))
        existing = cursor.fetchone()
        if existing:
            old_day = existing["day"]
            old_slot = existing["slot"]
            cursor.execute("""
                UPDATE orders 
                SET day = ?, slot = ?, notes = ?, created_by = ?, created_at = ?
                WHERE order_number = ?
            """, (day, slot, notes, username, now, order_num))
            conn.commit()
            cursor.execute("SELECT * FROM orders WHERE order_number = ?", (order_num,))
            row = dict(cursor.fetchone())
            conn.close()
            log_activity(username, "نقل طلب", f"نقل الطلب {order_num} من [{old_day}-{old_slot}] إلى [{day}-{slot}]")
            return True, f"تم نقل الطلب {order_num} من [{old_day} - رف {old_slot}] إلى [{day} - رف {slot}]", row
        
        cursor.execute("""
            INSERT INTO orders (order_number, day, slot, notes, status, created_by, created_at)
            VALUES (?, ?, ?, ?, 'في الرف', ?, ?)
        """, (order_num, day, slot, notes, username, now))
        conn.commit()
        order_id = cursor.lastrowid
        cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = dict(cursor.fetchone())
        conn.close()
        log_activity(username, "إضافة طلب", f"إضافة الطلب {order_num} إلى [{day} - رف {slot}]")
        return True, f"تمت إضافة الطلب {order_num} بنجاح إلى [{day} - رف {slot}]", row
    except Exception as e:
        conn.close()
        return False, f"حدث خطأ أثناء الإضافة: {str(e)}", None

def add_orders_bulk(orders_data: List[Dict], username: str = "admin") -> Dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    success_count = 0
    updated_count = 0
    errors = []
    
    for item in orders_data:
        order_num = clean_order_number(item.get("order_number"))
        day = str(item.get("day", "")).strip()
        slot = item.get("slot")
        notes = str(item.get("notes", "")).strip()
        
        if not order_num:
            errors.append("رقم طلب فارغ تم تخطيه")
            continue
            
        if day not in DAYS_OF_WEEK:
            errors.append(f"الطلب {order_num}: اليوم '{day}' غير مسموح")
            continue
            
        try:
            slot = int(slot)
            if slot not in SLOTS:
                errors.append(f"الطلب {order_num}: الرف {slot} خارج النطاق (0-9)")
                continue
        except (ValueError, TypeError):
            errors.append(f"الطلب {order_num}: رقم الرف غير صالح")
            continue
            
        try:
            cursor.execute("SELECT id FROM orders WHERE order_number = ?", (order_num,))
            existing = cursor.fetchone()
            if existing:
                cursor.execute("""
                    UPDATE orders SET day = ?, slot = ?, notes = ?, created_by = ?, created_at = ?
                    WHERE order_number = ?
                """, (day, slot, notes, username, now, order_num))
                updated_count += 1
            else:
                cursor.execute("""
                    INSERT INTO orders (order_number, day, slot, notes, status, created_by, created_at)
                    VALUES (?, ?, ?, ?, 'في الرف', ?, ?)
                """, (order_num, day, slot, notes, username, now))
                success_count += 1
        except Exception as e:
            errors.append(f"خطأ في الطلب {order_num}: {str(e)}")
            
    conn.commit()
    conn.close()
    log_activity(username, "إضافة جماعية / إكسل", f"معالجة {success_count + updated_count} طلب (جديد: {success_count}, تحديث: {updated_count})")
    return {
        "success": True,
        "added": success_count,
        "updated": updated_count,
        "total_processed": success_count + updated_count,
        "errors": errors
    }

def get_orders(day: Optional[str] = None, slot: Optional[int] = None, search: Optional[str] = None) -> List[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    
    if day:
        query += " AND day = ?"
        params.append(day)
    if slot is not None:
        query += " AND slot = ?"
        params.append(int(slot))
    if search:
        query += " AND (order_number LIKE ? OR notes LIKE ?)"
        s = f"%{search.strip()}%"
        params.extend([s, s])
        
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_order_by_number(order_number: str) -> Optional[Dict]:
    order_num = clean_order_number(order_number)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE order_number = ?", (order_num,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_order(order_id: int, username: str = "admin") -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT order_number, day, slot FROM orders WHERE id = ?", (order_id,))
    ord_row = cursor.fetchone()
    cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    if affected > 0 and ord_row:
        log_activity(username, "حذف طلب", f"حذف الطلب {ord_row['order_number']} من [{ord_row['day']}-{ord_row['slot']}]")
    return affected > 0

def delete_orders_bulk(order_ids: List[int], username: str = "admin") -> int:
    if not order_ids:
        return 0
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in order_ids)
    cursor.execute(f"DELETE FROM orders WHERE id IN ({placeholders})", order_ids)
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        log_activity(username, "حذف طلبات متعددة", f"حذف {affected} طلب من الرفوف")
    return affected

def clear_shelf(day: str, slot: int, username: str = "admin") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM orders WHERE day = ? AND slot = ?", (day, slot))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        log_activity(username, "إفراغ رف", f"إفراغ الرف [{day}-{slot}] بحذف {affected} طلب")
    return affected

def clear_day(day: str, username: str = "admin") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM orders WHERE day = ?", (day,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        log_activity(username, "إفراغ يوم بالكامل", f"إفراغ جميع رفوف يوم [{day}] بحذف {affected} طلب")
    return affected

def clear_all(username: str = "admin") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM orders")
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        log_activity(username, "إفراغ النظام كاملاً", f"تصفير الرفوف بالكامل بحذف {affected} طلب")
    return affected

def move_orders(order_ids: List[int], target_day: str, target_slot: int, username: str = "admin") -> int:
    if not order_ids or target_day not in DAYS_OF_WEEK or target_slot not in SLOTS:
        return 0
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in order_ids)
    params = [target_day, target_slot] + order_ids
    cursor.execute(f"UPDATE orders SET day = ?, slot = ? WHERE id IN ({placeholders})", params)
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        log_activity(username, "نقل طلبات", f"نقل {affected} طلب إلى [{target_day}-{target_slot}]")
    return affected

def get_stats() -> Dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM orders")
    total = cursor.fetchone()["total"]
    
    cursor.execute("SELECT day, COUNT(*) as count FROM orders GROUP BY day")
    day_counts = {d: 0 for d in DAYS_OF_WEEK}
    for row in cursor.fetchall():
        if row["day"] in day_counts:
            day_counts[row["day"]] = row["count"]
            
    cursor.execute("SELECT slot, COUNT(*) as count FROM orders GROUP BY slot")
    slot_counts = {s: 0 for s in SLOTS}
    for row in cursor.fetchall():
        if row["slot"] in slot_counts:
            slot_counts[row["slot"]] = row["count"]
            
    cursor.execute("SELECT day, slot, COUNT(*) as count FROM orders GROUP BY day, slot")
    matrix = {}
    for d in DAYS_OF_WEEK:
        matrix[d] = {s: 0 for s in SLOTS}
    for row in cursor.fetchall():
        d = row["day"]
        s = row["slot"]
        if d in matrix and s in matrix[d]:
            matrix[d][s] = row["count"]
            
    cursor.execute("SELECT COUNT(*) as u_count FROM users")
    user_count = cursor.fetchone()["u_count"]

    conn.close()
    return {
        "total_orders": total,
        "by_day": day_counts,
        "by_slot": slot_counts,
        "matrix": matrix,
        "total_users": user_count
    }
