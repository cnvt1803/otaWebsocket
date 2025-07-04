from fastapi import Request
from fastapi import Header
from jose import jwt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from supabase import create_client, Client
from fastapi.middleware.cors import CORSMiddleware
import requests
import json
import uvicorn
import os
# ✅ Khởi tạo FastAPI
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ✅ Kết nối Supabase
SUPABASE_URL = "https://zkzyawzjmllvqzmedsxd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inprenlhd3pqbWxsdnF6bWVkc3hkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MTQyOTAzNSwiZXhwIjoyMDY3MDA1MDM1fQ.IG8eGax0lUxkUOW8TpJ6M0QvSafB-gM2NWsg6wIOlTU"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ✅ Danh sách thiết bị đang kết nối
connected_devices: dict[str, WebSocket] = {}

# ✅ Hàm lấy OTA mới nhất


def get_latest_ota(device_name, current_version):
    path = f"ota_muti/{device_name}/ota-latest.json"
    try:
        file = supabase.storage.from_("ota").download(path)
        ota = json.loads(file.decode("utf-8"))
        if ota["version"] != current_version:
            return ota
    except Exception as e:
        print("❌ OTA fetch error:", e)
    return None

# ✅ Cập nhật DB khi ESP OTA xong


def update_device(device_id, version):
    supabase.table("devices") \
        .update({"version": version, "status": "done"}) \
        .eq("device_id", device_id) \
        .execute()

# ✅ WebSocket endpoint cho ESP kết nối


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    device_id = None

    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            action = data.get("action")

            if action == "register_esp":
                device_id = data["device_id"]
                connected_devices[device_id] = websocket
                print(f"🟢 ESP {device_id} đã kết nối")

            elif action == "ota_done":
                device_id = data["device_id"]
                new_version = data["version"]
                print(f"✅ ESP {device_id} đã cập nhật lên v{new_version}")
                update_device(device_id, new_version)
                await websocket.send_json({
                    "action": "done_ack",
                    "message": "🎉 Cập nhật thành công!"
                })

    except WebSocketDisconnect:
        if device_id and device_id in connected_devices:
            print(f"🔴 ESP {device_id} ngắt kết nối")
            del connected_devices[device_id]

    except Exception as e:
        print("⚠️ Lỗi xử lý:", e)

# ✅ API cho Web UI: gửi yêu cầu cập nhật OTA


@app.post("/api/update-device")
async def update_device_api(request: Request):
    body = await request.json()
    device_id = body.get("device_id")

    # 🔍 Lấy thiết bị theo device_id
    res = supabase.table("devices").select(
        "*").eq("device_id", device_id).single().execute()

    if not res.data:
        return JSONResponse({"error": "Thiết bị không tồn tại"}, status_code=404)

    device = res.data
    current_version = device["version"]
    device_name = device["name"]
    user_id = device["user_id"]

    print(f"📤 Gửi OTA cho {device_id} ({device_name})...")

    # � Lấy OTA mới nhất nếu có
    ota = get_latest_ota(device_name, current_version)
    if not ota:
        return JSONResponse({"message": "Thiết bị đã ở phiên bản mới nhất"})

    if device_id in connected_devices:
        ws = connected_devices[device_id]

        # ✅ Tạo device_id format mới: <name>_<user_id>_<device_id>
        ota_with_device_id = {
            "device_id": f"{device_name}_{user_id}_{device_id}",
            **ota
        }

        # 📤 Gửi dữ liệu OTA qua WebSocket
        await ws.send_json(ota_with_device_id)

        # 🛠️ Cập nhật trạng thái thiết bị thành "waiting"
        supabase.table("devices").update({"status": "waiting"}).eq(
            "device_id", device_id).execute()

        print(f"� Đã gửi OTA cho ESP {device_id}")
        return {"message": "Đã gửi OTA", "ota": ota_with_device_id}

    else:
        return JSONResponse({"error": "ESP chưa kết nối"}, status_code=400)


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    email = body.get("email")
    password = body.get("password")

    if not email or not password:
        return JSONResponse({"error": "Thiếu email hoặc mật khẩu"}, status_code=400)

    try:
        url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
        headers = {
            "apikey": SUPABASE_KEY,  # dùng anon hoặc service role key đều được
            "Content-Type": "application/json"
        }
        payload = {
            "email": email,
            "password": password
        }

        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            return JSONResponse({"error": response.json()}, status_code=401)

        data = response.json()
        access_token = data["access_token"]
        user_id = data["user"]["id"]

        return JSONResponse({
            "message": "✅ Đăng nhập thành công",
            "access_token": access_token,
            "user_id": user_id
        })

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/register")
async def register_user(request: Request):
    body = await request.json()
    email = body.get("email")
    password = body.get("password")
    name = body.get("name")
    role = body.get("role", "user")

    if not email or not password:
        return JSONResponse({"error": "Thiếu email hoặc password"}, status_code=400)

    try:
        # Gửi POST trực tiếp tới Supabase Auth API
        url = f"{SUPABASE_URL}/auth/v1/admin/users"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "email": email,
            "password": password
        }

        response = requests.post(url, json=payload, headers=headers)
        if response.status_code >= 300:
            return JSONResponse({"error": response.json()}, status_code=response.status_code)

        user_id = response.json()["id"]

        # Gán role vào bảng user_profiles
        supabase.table("user_profiles").insert({
            "id": user_id,
            "role": role,
            "name": name
        }).execute()

        return JSONResponse({"message": "Tạo tài khoản thành công", "user_id": user_id})

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# 👇 Thay bằng key của bạn
SUPABASE_JWT_SECRET = "koJJ0d58iKJYPdhEZhBIBKLEXno9HRWgE6eCC7SVsd/HrbcPfSsxgvppGthK0ciLIBM+RSUSLSnjttsQ+wJ2sA=="


def decode_token(token: str):
    try:
        payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")  # chính là user_id
    except Exception as e:
        print("❌ Token decode error:", e)
        return None


@app.post("/api/add-device")
async def add_device(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse({"error": "Thiếu token"}, status_code=401)

    token = authorization.replace("Bearer ", "")
    user_id = decode_token(token)

    if not user_id:
        return JSONResponse({"error": "Token không hợp lệ"}, status_code=403)

    body = await request.json()
    device_id = body.get("device_id")
    name = body.get("name")
    location = body.get("location")

    if not all([device_id, name, location]):
        return JSONResponse({"error": "Thiếu thông tin thiết bị"}, status_code=400)

    # ✅ Kiểm tra tồn tại
    res = supabase.table("devices").select(
        "*").eq("device_id", device_id).execute()
    if res.data:
        return JSONResponse({"error": "Thiết bị đã tồn tại"}, status_code=409)

    # ✅ Thêm thiết bị cho user đang đăng nhập
    supabase.table("devices").insert({
        "user_id": user_id,
        "device_id": device_id,
        "name": name,
        "version": "1.0.0",
        "location": location,
        "status": "none"
    }).execute()

    return JSONResponse({"message": "✅ Thiết bị đã được thêm cho user đăng nhập"})


# 🔁 Chạy local với port=8765 hoặc Render tự chọn PORT
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
