import os
import io
from typing import List, Optional, Dict
from fastapi import FastAPI, UploadFile, File, Form, Query, HTTPException, Request, Response, Depends, Cookie
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database
import qr_service
import excel_service

app = FastAPI(title="نظام الرفوف الإلكترونية - شركة مرسال زيونة للتوصيل السريع (ZMC)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.on_event("startup")
def startup_event():
    database.init_db()

# --- Auth Dependency ---
def get_current_user(request: Request) -> Optional[Dict]:
    # Check cookie or Authorization header
    token = request.cookies.get("zmc_session")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
    if not token:
        return None
    return database.get_user_by_session(token)

def require_auth(request: Request) -> Dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="يرجى تسجيل الدخول أولاً")
    return user

def require_admin(user: Dict = Depends(require_auth)) -> Dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="هذه العملية مخصصة لمدير النظام فقط")
    return user

# --- Pydantic Schemas ---
class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreateRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: Optional[str] = "employee"
    can_add: Optional[int] = 1
    can_delete: Optional[int] = 0
    can_edit: Optional[int] = 0
    can_export: Optional[int] = 0

class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    can_add: Optional[int] = None
    can_delete: Optional[int] = None
    can_edit: Optional[int] = None
    can_export: Optional[int] = None
    is_active: Optional[int] = None

class SingleOrderRequest(BaseModel):
    order_number: Optional[str] = None
    order_numbers: Optional[List[str]] = None
    day: str
    slot: int
    notes: Optional[str] = ""

class MoveOrdersRequest(BaseModel):
    order_ids: List[int]
    target_day: str
    target_slot: int

class BatchDeleteRequest(BaseModel):
    order_ids: List[int]

class ShelfClearRequest(BaseModel):
    day: str
    slot: Optional[int] = None

# --- HTML Pages ---
@app.get("/login", response_class=HTMLResponse)
def login_page():
    path = os.path.join(TEMPLATES_DIR, "login.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/", response_class=HTMLResponse)
def index_page():
    path = os.path.join(TEMPLATES_DIR, "index.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/shelf-view", response_class=HTMLResponse)
def shelf_view_page():
    path = os.path.join(TEMPLATES_DIR, "shelf_view.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/print-labels", response_class=HTMLResponse)
def print_labels_page():
    path = os.path.join(TEMPLATES_DIR, "print_labels.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

# --- Auth APIs ---
@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response):
    user = database.authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=400, detail="اسم المستخدم أو كلمة المرور غير صحيحة")
    
    token = database.create_session(user["id"])
    response.set_cookie(
        key="zmc_session", 
        value=token, 
        httponly=False, 
        max_age=7*24*3600, 
        path="/"
    )
    database.log_activity(user["username"], "تسجيل دخول", f"تسجيل دخول ناجح للمستخدم {user['full_name']}")
    return {"success": True, "token": token, "user": user}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("zmc_session")
    if token:
        database.delete_session(token)
    response.delete_cookie(key="zmc_session", path="/")
    return {"success": True, "message": "تم تسجيل الخروج بنجاح"}

@app.get("/api/auth/me")
def get_me(request: Request):
    user = get_current_user(request)
    if not user:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": user}

# --- User Management APIs (Admin Only) ---
@app.get("/api/users")
def list_users(admin: Dict = Depends(require_admin)):
    return {"users": database.get_all_users()}

@app.post("/api/users")
def create_new_user(req: UserCreateRequest, admin: Dict = Depends(require_admin)):
    success, msg, created = database.create_user(
        username=req.username,
        password=req.password,
        full_name=req.full_name,
        role=req.role or "employee",
        can_add=req.can_add if req.can_add is not None else 1,
        can_delete=req.can_delete if req.can_delete is not None else 0,
        can_edit=req.can_edit if req.can_edit is not None else 0,
        can_export=req.can_export if req.can_export is not None else 0,
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    database.log_activity(admin["username"], "إنشاء حساب موظف", f"إنشاء حساب للموظف {req.username} ({req.full_name})")
    return {"success": True, "message": msg, "user": created}

@app.put("/api/users/{user_id}")
def update_user_endpoint(user_id: int, req: UserUpdateRequest, admin: Dict = Depends(require_admin)):
    success, msg = database.update_user(
        user_id=user_id,
        full_name=req.full_name,
        password=req.password,
        role=req.role,
        can_add=req.can_add,
        can_delete=req.can_delete,
        can_edit=req.can_edit,
        can_export=req.can_export,
        is_active=req.is_active
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    database.log_activity(admin["username"], "تعديل حساب موظف", f"تعديل بيانات/صلاحيات المستخدم معرّف #{user_id}")
    return {"success": True, "message": msg}

@app.delete("/api/users/{user_id}")
def delete_user_endpoint(user_id: int, admin: Dict = Depends(require_admin)):
    success, msg = database.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    database.log_activity(admin["username"], "حذف موظف", msg)
    return {"success": True, "message": msg}

@app.get("/api/activity-logs")
def get_logs(admin: Dict = Depends(require_admin)):
    return {"logs": database.get_activity_logs(limit=40)}

# --- Core Shelves & Orders APIs ---

@app.get("/api/network-info")
def get_network_info(request: Request):
    host_header = request.headers.get("host", "")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    
    # If running on public domain / cloud hosting
    if host_header and not any(local_k in host_header for local_k in ["localhost", "127.0.0.1", "192.168.", "10.0.", "172."]):
        host_url = f"{proto}://{host_header}"
        ip = host_header
        port = 443 if proto == "https" else 80
    else:
        ip = qr_service.get_local_ip()
        port = request.url.port or 8000
        host_url = f"http://{ip}:{port}"

    qr_data_url = qr_service.generate_qr_base64(host_url)
    return {
        "company_name": "شركة مرسال زيونة للتوصيل السريع (ZMC)",
        "local_ip": ip,
        "port": port,
        "host_url": host_url,
        "qr_base64": qr_data_url,
        "days": database.DAYS_OF_WEEK,
        "slots": database.SLOTS
    }

@app.get("/api/stats")
def get_stats():
    return database.get_stats()

@app.get("/api/orders")
def get_orders(
    day: Optional[str] = None, 
    slot: Optional[int] = None, 
    search: Optional[str] = None
):
    orders = database.get_orders(day=day, slot=slot, search=search)
    return {"orders": orders, "count": len(orders)}

@app.get("/api/orders/lookup/{order_number}")
def lookup_order(order_number: str):
    order = database.get_order_by_number(order_number)
    if not order:
        return {"found": False, "message": f"الطلب {order_number} غير موجود في أي رف"}
    return {"found": True, "order": order}

@app.post("/api/orders")
def create_order(req: SingleOrderRequest, request: Request):
    user = get_current_user(request)
    # Check add permission
    if user and user.get("role") != "admin" and not user.get("can_add"):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية إضافة الطلبات للرفوف")

    username = user["username"] if user else "guest"

    numbers = []
    if req.order_numbers:
        numbers.extend(req.order_numbers)
    if req.order_number:
        numbers.append(req.order_number)

    clean_nums = []
    for n in numbers:
        cleaned = database.clean_order_number(n)
        if cleaned and cleaned not in clean_nums:
            clean_nums.append(cleaned)

    if not clean_nums:
        raise HTTPException(status_code=400, detail="يرجى كتابة رقم طلب واحد على الأقل")

    if req.day not in database.DAYS_OF_WEEK:
        raise HTTPException(status_code=400, detail=f"اليوم '{req.day}' غير صحيح (أيام العمل: السبت إلى الخميس)")

    if req.slot not in database.SLOTS:
        raise HTTPException(status_code=400, detail="رقم الرف يجب أن يكون من 0 إلى 9")

    if len(clean_nums) == 1:
        success, msg, item = database.add_order(clean_nums[0], req.day, req.slot, req.notes or "", username=username)
        if not success:
            raise HTTPException(status_code=400, detail=msg)
        return {"success": True, "message": msg, "order": item, "count": 1}
    else:
        items = [{"order_number": num, "day": req.day, "slot": req.slot, "notes": req.notes or ""} for num in clean_nums]
        result = database.add_orders_bulk(items, username=username)
        return {
            "success": True, 
            "message": f"تمت إضافة/تحديث {result['total_processed']} طلب بنجاح إلى [{req.day} - رف {req.slot}]",
            "details": result,
            "count": result["total_processed"]
        }

@app.delete("/api/orders/{order_id}")
def delete_order_endpoint(order_id: int, request: Request):
    user = get_current_user(request)
    if user and user.get("role") != "admin" and not user.get("can_delete"):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية حذف أو تسليم الطلبات")

    username = user["username"] if user else "guest"
    success = database.delete_order(order_id, username=username)
    if not success:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    return {"success": True, "message": "تم حذف/تسليم الطلب بنجاح"}

@app.post("/api/orders/batch-delete")
def batch_delete_orders(req: BatchDeleteRequest, request: Request):
    user = get_current_user(request)
    if user and user.get("role") != "admin" and not user.get("can_delete"):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية حذف الطلبات")

    username = user["username"] if user else "guest"
    count = database.delete_orders_bulk(req.order_ids, username=username)
    return {"success": True, "deleted_count": count, "message": f"تم حذف {count} طلب"}

@app.post("/api/orders/move")
def move_orders_endpoint(req: MoveOrdersRequest, request: Request):
    user = get_current_user(request)
    if user and user.get("role") != "admin" and not user.get("can_edit"):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية تعديل ونقل الطلبات")

    username = user["username"] if user else "guest"
    if req.target_day not in database.DAYS_OF_WEEK:
        raise HTTPException(status_code=400, detail="اليوم غير صحيح")
    if req.target_slot not in database.SLOTS:
        raise HTTPException(status_code=400, detail="رقم الرف غير صحيح (0-9)")
        
    count = database.move_orders(req.order_ids, req.target_day, req.target_slot, username=username)
    return {
        "success": True, 
        "moved_count": count, 
        "message": f"تم نقل {count} طلب إلى [{req.target_day} - رف {req.target_slot}]"
    }

@app.post("/api/shelves/clear")
def clear_shelf_endpoint(req: ShelfClearRequest, request: Request):
    user = get_current_user(request)
    if user and user.get("role") != "admin" and not user.get("can_delete"):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية إفراغ الرفوف")

    username = user["username"] if user else "guest"
    if req.day not in database.DAYS_OF_WEEK:
        raise HTTPException(status_code=400, detail="اليوم غير صحيح")
        
    if req.slot is not None:
        count = database.clear_shelf(req.day, int(req.slot), username=username)
        msg = f"تم إفراغ الرف [{req.day} - رف {req.slot}] بحذف {count} طلب"
    else:
        count = database.clear_day(req.day, username=username)
        msg = f"تم إفراغ جميع رفوف يوم [{req.day}] بحذف {count} طلب"
        
    return {"success": True, "cleared_count": count, "message": msg}

@app.post("/api/shelves/clear-all")
def clear_all_shelves(admin: Dict = Depends(require_admin)):
    count = database.clear_all(username=admin["username"])
    return {"success": True, "cleared_count": count, "message": f"تم إفراغ النظام بالكامل وحذف {count} طلب"}

# --- Excel Import / Export ---
@app.get("/api/download-template")
def download_excel_template():
    excel_bytes = excel_service.generate_template()
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=zmc_shelf_orders_template.xlsx"}
    )

@app.post("/api/import-excel")
async def import_excel_file(
    file: UploadFile = File(...),
    default_day: Optional[str] = Form(None),
    default_slot: Optional[str] = Form(None),
    auto_distribute: Optional[str] = Form("false"),
    request: Request = None
):
    user = get_current_user(request)
    if user and user.get("role") != "admin" and not user.get("can_add"):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية إضافة الطلبات عبر الإكسل")

    username = user["username"] if user else "guest"

    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="يجب رفع ملف إكسل بصيغة .xlsx")
        
    content = await file.read()
    auto_dist = str(auto_distribute).lower() in ("true", "1", "yes")
    
    parsed_slot = None
    if default_slot is not None and default_slot != "":
        try:
            parsed_slot = int(default_slot)
        except Exception:
            parsed_slot = None

    parsed_orders, parse_warnings = excel_service.parse_excel_file(
        content,
        default_day=default_day if default_day else None,
        default_slot=parsed_slot,
        auto_distribute_by_digit=auto_dist
    )

    if not parsed_orders:
        detail_msg = "لم يتم العثور على أي طلبات صالحة للإضافة."
        if parse_warnings:
            detail_msg += " " + " | ".join(parse_warnings[:3])
        raise HTTPException(status_code=400, detail=detail_msg)

    result = database.add_orders_bulk(parsed_orders, username=username)
    return {
        "success": True,
        "message": f"تمت معالجة {result['total_processed']} طلب (إضافة: {result['added']}, تحديث: {result['updated']})",
        "result": result,
        "warnings": parse_warnings
    }

@app.get("/api/export-excel")
def export_excel(
    day: Optional[str] = None, 
    slot: Optional[int] = None,
    search: Optional[str] = None,
    request: Request = None
):
    user = get_current_user(request)
    if user and user.get("role") != "admin" and not user.get("can_export"):
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية تصدير البيانات")

    orders = database.get_orders(day=day, slot=slot, search=search)
    title = "طلبات_مرسال_زيونة"
    if day and slot is not None:
        title = f"ZMC_رف_{day}_{slot}"
    elif day:
        title = f"ZMC_رفوف_{day}"
    elif slot is not None:
        title = f"ZMC_رفوف_رقم_{slot}"

    excel_bytes = excel_service.export_orders_to_excel(orders, sheet_title=title)
    filename = f"{title}.xlsx"
    import urllib.parse
    encoded_filename = urllib.parse.quote(filename)
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
    )

# --- QR Code APIs ---
@app.get("/api/qr/generate")
def get_qr_image(
    request: Request,
    day: Optional[str] = None,
    slot: Optional[int] = None,
    base_url: Optional[str] = None,
    box_size: int = 7
):
    if not base_url:
        host_header = request.headers.get("host", "")
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if host_header and not any(local_k in host_header for local_k in ["localhost", "127.0.0.1", "192.168."]):
            base_url = f"{proto}://{host_header}"
        else:
            ip = qr_service.get_local_ip()
            base_url = f"http://{ip}:8000"
        
    if day and slot is not None:
        url = qr_service.build_shelf_url(base_url, day, slot)
    elif day:
        url = qr_service.build_shelf_url(base_url, day)
    elif slot is not None:
        url = qr_service.build_number_url(base_url, slot)
    else:
        url = base_url

    qr_b64 = qr_service.generate_qr_base64(url, box_size=box_size)
    return {
        "url": url,
        "qr_base64": qr_b64
    }

@app.get("/api/qr/labels-data")
def get_all_labels_data(
    request: Request,
    base_url: Optional[str] = None,
    filter_day: Optional[str] = None
):
    if not base_url:
        host_header = request.headers.get("host", "")
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if host_header and not any(local_k in host_header for local_k in ["localhost", "127.0.0.1", "192.168."]):
            base_url = f"{proto}://{host_header}"
        else:
            ip = qr_service.get_local_ip()
            base_url = f"http://{ip}:8000"

    days = [filter_day] if filter_day and filter_day in database.DAYS_OF_WEEK else database.DAYS_OF_WEEK
    stats = database.get_stats()
    matrix = stats.get("matrix", {})

    labels = []
    for d in days:
        for s in database.SLOTS:
            url = qr_service.build_shelf_url(base_url, d, s)
            b64 = qr_service.generate_qr_base64(url, box_size=5, border=1)
            count = matrix.get(d, {}).get(s, 0)
            labels.append({
                "day": d,
                "slot": s,
                "label_title": f"{d} - رف {s}",
                "company": "مرسال زيونة (ZMC)",
                "url": url,
                "qr_base64": b64,
                "orders_count": count
            })

    number_labels = []
    for s in database.SLOTS:
        url = qr_service.build_number_url(base_url, s)
        b64 = qr_service.generate_qr_base64(url, box_size=5, border=1)
        number_labels.append({
            "slot": s,
            "label_title": f"رف رقم {s} (عام)",
            "company": "مرسال زيونة (ZMC)",
            "url": url,
            "qr_base64": b64,
            "orders_count": stats.get("by_slot", {}).get(s, 0)
        })

    return {
        "base_url": base_url,
        "shelf_labels": labels,
        "number_labels": number_labels
    }

# --- SEO & Googlebot Endpoints ---
@app.get("/robots.txt", response_class=FileResponse)
def get_robots_txt():
    path = os.path.join(STATIC_DIR, "robots.txt")
    return FileResponse(path, media_type="text/plain")

@app.get("/sitemap.xml", response_class=FileResponse)
def get_sitemap_xml():
    path = os.path.join(STATIC_DIR, "sitemap.xml")
    return FileResponse(path, media_type="application/xml")

if __name__ == "__main__":
    import uvicorn
    ip = qr_service.get_local_ip()
    port = int(os.environ.get("PORT", 8000))
    print("=" * 60)
    print(" 🚀 شركة مرسال زيونة للتوصيل السريع (ZMC)")
    print(" نظام الرفوف الإلكترونية وتوزيع الطرود يعمل الآن!")
    print(f" 💻 الرابط المحلي: http://localhost:{port}")
    print(f" 📱 الرابط عبر الواي فاي: http://{ip}:{port}")
    print("=" * 60)
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
