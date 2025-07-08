from fastapi.responses import PlainTextResponse
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
import asyncio
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
connected_devices: dict[str, dict[str, WebSocket]] = {}
reconnect_tasks: dict[str, asyncio.Task] = {}
# ✅ Hàm lấy OTA mới nhất


@app.get("/")
async def root():
    return PlainTextResponse("WebSocket OTA Server is running.")


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


def update_device(device_id, version):
    supabase.table("devices") \
        .update({"version": version, "status": "done"}) \
        .eq("device_id", device_id) \
        .execute()


async def handle_reconnect_timeout(device_id: str):
    try:
        await asyncio.sleep(30)
        print(f"⏰ ESP {device_id} không reconnect sau 30s! Ghi cảnh báo.")
        supabase.table("devices").update({
            "warning": "Thiết bị mất kết nối hơn 30 giây"
        }).eq("device_id", device_id).execute()
    except asyncio.CancelledError:
        print(f"✅ ESP {device_id} đã reconnect — bỏ cảnh báo")


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    print(f"🌐 WebSocket /ws/{user_id} đã được gọi")
    await websocket.accept()
    device_id = None

    try:
        while True:
            print(f"{user_id}] Chờ tin nhắn từ ESP...")
            message = await websocket.receive_text()
            print(f"[{user_id}] Nhận từ ESP: {message}")

            try:
                data = json.loads(message)
                command = data.get("command")
                device_id = data.get("device_id")

                if command == "REGISTER_DEVICE":
                    if user_id not in connected_devices:
                        connected_devices[user_id] = {}
                    connected_devices[user_id][device_id] = websocket

                    if device_id in reconnect_tasks:
                        reconnect_tasks[device_id].cancel()
                        del reconnect_tasks[device_id]

                    print(f"ESP {device_id} (user {user_id}) đã kết nối")
                    print("thiết bị đang kết nối:",
                          list(connected_devices[user_id].keys()))

                    update_data = {"is_connect": "new"}

                    if "version" in data:
                        version = data["version"]
                        update_data["version"] = version
                        print(f"📌 Phiên bản firmware: {version}")

                    supabase.table("devices").update(update_data).eq(
                        "device_id", device_id).execute()

                elif command == "UPDATE_FIRMWARE_APPROVE":
                    print(
                        f"ESP {device_id} bắt đầu cập nhật: v{data.get('version')}")

                elif command == "UPDATE_FIRMWARE_SUCCESSFULLY":
                    new_version = data.get("version")
                    print(
                        f"ESP {device_id} cập nhật thành công v{new_version}")
                    update_device(device_id, new_version)
                    await websocket.send_json({
                        "command": "ACK_SUCCESS",
                        "message": "Đã nhận xác nhận cập nhật thành công!"
                    })

                elif command == "UPDATE_FIRMWARE_FAILED":
                    failed_version = data.get("version")
                    error_code = data.get("error_code", "unknown")
                    reason = data.get("reason", "Không rõ nguyên nhân")

                    print(
                        f"ESP {device_id} cập nhật v{failed_version} thất bại")
                    print(f"Lỗi: [{error_code}] - {reason}")

                    supabase.table("devices").update({
                        "status": "failed",
                        "error_code": error_code,
                        "reason": reason
                    }).eq("device_id", device_id).execute()

                    await websocket.send_json({
                        "command": "ACK_FAILED",
                        "message": "Thiết bị đã có phiên bản mới nhất hoặc lỗi trong quá trình cập nhật.",
                        "error_code": error_code,
                        "reason": reason
                    })

                elif command == "REGISTER_NEW_DEVICE":
                    device_name = data.get("name")
                    version = data.get("version", "unknown")

                    if not device_name:
                        await websocket.send_json({
                            "command": "ACK_FAILED",
                            "message": "Thiếu tên thiết bị!"
                        })
                        return

                    insert_result = supabase.table("devices").insert({
                        "user_id": user_id,
                        "name": device_name,
                        "version": version,
                        "status": "new",
                        "is_connect": "online"
                    }).execute()

                    if insert_result.data and len(insert_result.data) > 0:
                        device_id = insert_result.data[0]["device_id"]

                        if user_id not in connected_devices:
                            connected_devices[user_id] = {}
                        connected_devices[user_id][device_id] = websocket

                        print(
                            f"Đã tạo và kết nối thiết bị mới: {device_id} cho user {user_id}")
                        print("Thiết bị đang kết nối:",
                              list(connected_devices[user_id].keys()))

                        await websocket.send_json({
                            "command": "ACK_NEW_DEVICE",
                            "device_id": device_id,
                            "message": "Thiết bị mới đã được tạo"
                        })
                    else:
                        await websocket.send_json({
                            "command": "ACK_FAILED",
                            "message": "Không thể tạo thiết bị mới"
                        })

                elif command == "LOG":
                    print(f"Log từ {device_id}: {data}")

                else:
                    print(f"Lệnh không xác định: {command}")

            except Exception as e:
                print("❌ Lỗi xử lý frame:", e)

    except WebSocketDisconnect:
        print(f"🔴 ESP {device_id} (user {user_id}) ngắt kết nối")
        if user_id in connected_devices and device_id in connected_devices[user_id]:
            del connected_devices[user_id][device_id]

        supabase.table("devices").update({"is_connect": "offline"}).eq(
            "device_id", device_id).execute()

        task = asyncio.create_task(handle_reconnect_timeout(device_id))
        reconnect_tasks[device_id] = task


# @app.post("/api/update-device")
# async def update_device_api(request: Request):
#     body = await request.json()
#     device_id = body.get("device_id")

#     res = supabase.table("devices").select(
#         "*").eq("device_id", device_id).single().execute()
#     if not res.data:
#         return JSONResponse({"error": "Thiết bị không tồn tại"}, status_code=404)

#     device = res.data
#     current_version = device["version"]
#     device_name = device["name"]
#     user_id = device["user_id"]

#     print(f"🚀 Gửi OTA cho {device_id} ({device_name}) thuộc user {user_id}")

#     ota = get_latest_ota(device_name, current_version)
#     if not ota:
#         return JSONResponse({"message": "Thiết bị đã ở phiên bản mới nhất"})

#     if user_id in connected_devices and device_id in connected_devices[user_id]:
#         ws = connected_devices[user_id][device_id]

#         ota_with_device_id = {
#             "device_id": device_id,
#             **ota
#         }

#         await ws.send_json(ota_with_device_id)

#         supabase.table("devices").update({"status": "waiting"}).eq(
#             "device_id", device_id).execute()

#         print(f"✅ Đã gửi OTA cho ESP {device_id}")
#         return {"message": "Đã gửi OTA", "ota": ota_with_device_id}
#     else:
#         return JSONResponse({"error": "ESP chưa kết nối"}, status_code=400)
@app.post("/api/update-device")
async def update_device_api(request: Request):
    body = await request.json()
    device_ids = body.get("device_ids")  # <- giờ nhận 1 list

    if not device_ids or not isinstance(device_ids, list):
        return JSONResponse({"error": "Vui lòng cung cấp danh sách device_ids"}, status_code=400)

    results = []

    for device_id in device_ids:
        try:
            res = supabase.table("devices").select(
                "*").eq("device_id", device_id).single().execute()
            if not res.data:
                results.append(
                    {"device_id": device_id, "status": "❌ Không tồn tại"})
                continue

            device = res.data
            current_version = device["version"]
            device_name = device["name"]
            user_id = device["user_id"]

            print(f"🚀 Xử lý OTA cho {device_id} ({device_name})")

            ota = get_latest_ota(device_name, current_version)
            if not ota:
                results.append(
                    {"device_id": device_id, "status": "✅ Đã ở phiên bản mới nhất"})
                continue

            if user_id in connected_devices and device_id in connected_devices[user_id]:
                ws = connected_devices[user_id][device_id]

                ota_with_device_id = {
                    "device_id": device_id,
                    **ota
                }

                await ws.send_json(ota_with_device_id)

                supabase.table("devices").update({"status": "waiting"}).eq(
                    "device_id", device_id).execute()

                print(f"✅ Gửi OTA thành công cho ESP {device_id}")
                results.append(
                    {"device_id": device_id, "status": "✅ Đã gửi OTA"})
            else:
                results.append(
                    {"device_id": device_id, "status": "⚠️ ESP chưa kết nối"})

        except Exception as e:
            print(f"❌ Lỗi khi xử lý {device_id}: {e}")
            results.append(
                {"device_id": device_id, "status": f"❌ Lỗi: {str(e)}"})

    return {"results": results}


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
            "apikey": SUPABASE_KEY,
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
    phone = body.get("phone")
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
            "password": password,
        }

        response = requests.post(url, json=payload, headers=headers)
        if response.status_code >= 300:
            return JSONResponse({"error": response.json()}, status_code=response.status_code)

        user_id = response.json()["id"]

        # Gán role vào bảng user_profiles
        supabase.table("user_profiles").insert({
            "id": user_id,
            "role": role,
            "name": name,
            "email": email,
            "phone": phone
        }).execute()

        return JSONResponse({"message": "Tạo tài khoản thành công", "user_id": user_id})

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# 👇 Thay bằng key của bạn
SUPABASE_JWT_SECRET = "koJJ0d58iKJYPdhEZhBIBKLEXno9HRWgE6eCC7SVsd/HrbcPfSsxgvppGthK0ciLIBM+RSUSLSnjttsQ+wJ2sA=="


def decode_token(token: str):
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False}
        )
        print("✅ Token payload:", payload)
        return payload.get("sub")
    except Exception as e:
        print("❌ Token decode error:", e)
        return None


@app.post("/api/add-device")
async def add_device(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse({"error": "Thiếu token"}, status_code=401)

    token = authorization.replace("Bearer ", "").strip()
    user_id = decode_token(token)

    if not user_id:
        return JSONResponse({"error": "Token không hợp lệ"}, status_code=403)

    body = await request.json()
    name = body.get("name")
    location = body.get("location")

    if not all([name, location]):
        return JSONResponse({"error": "Thiếu thông tin thiết bị"}, status_code=400)

    try:
        insert_result = supabase.table("devices").insert({
            "user_id": user_id,
            "name": name,
            "version": "1.0.0",
            "location": location,
            "status": "none"
        }).execute()

        return JSONResponse({
            "message": "✅ Thiết bị đã được thêm",
            "device": insert_result.data[0]
        })

    except Exception as e:
        print("❌ Lỗi khi thêm thiết bị:", e)
        return JSONResponse({"error": "Không thể thêm thiết bị"}, status_code=500)


@app.delete("/api/delete-device")
async def delete_device(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse({"error": "Thiếu token"}, status_code=401)

    token = authorization.replace("Bearer ", "").strip()
    user_id = decode_token(token)

    if not user_id:
        return JSONResponse({"error": "Token không hợp lệ"}, status_code=403)

    body = await request.json()
    device_id = body.get("device_id")

    if not device_id:
        return JSONResponse({"error": "Thiếu device_id"}, status_code=400)

    res = supabase.table("devices").select("*").match({
        "user_id": user_id,
        "device_id": device_id
    }).execute()

    if not res.data:
        return JSONResponse({"error": "Thiết bị không tồn tại hoặc không thuộc quyền sở hữu"}, status_code=404)

    try:
        supabase.table("devices").delete().match({
            "user_id": user_id,
            "device_id": device_id
        }).execute()

        return JSONResponse({"message": f"✅ Đã xoá thiết bị {device_id}"})
    except Exception as e:
        print("❌ Lỗi khi xoá thiết bị:", e)
        return JSONResponse({"error": "Không thể xoá thiết bị"}, status_code=500)


@app.post("/api/update-device-info")
async def update_device_info(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse({"error": "Thiếu token"}, status_code=401)

    token = authorization.replace("Bearer ", "").strip()
    user_id = decode_token(token)

    if not user_id:
        return JSONResponse({"error": "Token không hợp lệ"}, status_code=403)

    body = await request.json()
    device_id = body.get("device_id")
    if not device_id:
        return JSONResponse({"error": "Thiếu device_id"}, status_code=400)

    # 🎯 Chỉ cho phép sửa 3 trường này
    allowed_fields = ["name", "location", "version"]
    update_data = {key: body[key] for key in allowed_fields if key in body}

    if not update_data:
        return JSONResponse({"error": "Không có trường hợp lệ để cập nhật"}, status_code=400)

    try:
        # 🔒 Kiểm tra quyền sở hữu thiết bị
        res = supabase.table("devices").select("user_id").eq(
            "device_id", device_id).single().execute()
        if not res.data:
            return JSONResponse({"error": "Thiết bị không tồn tại"}, status_code=404)

        if res.data["user_id"] != user_id:
            return JSONResponse({"error": "Bạn không có quyền sửa thiết bị này"}, status_code=403)

        # ✅ Tiến hành cập nhật
        result = supabase.table("devices") \
            .update(update_data) \
            .eq("device_id", device_id) \
            .execute()

        return JSONResponse({
            "message": "✅ Đã cập nhật thiết bị thành công",
            "device": result.data[0]
        })

    except Exception as e:
        print("❌ Lỗi cập nhật thiết bị:", e)
        return JSONResponse({"error": str(e)}, status_code=500)


# Lấy danh sách thiết bị của người dùng


@app.get("/api/my-devices")
async def get_my_devices(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse({"error": "Thiếu token"}, status_code=401)

    token = authorization.replace("Bearer ", "").strip()
    user_id = decode_token(token)

    if not user_id:
        return JSONResponse({"error": "Token không hợp lệ"}, status_code=403)

    try:
        response = supabase.table("devices").select(
            "device_id, name, version, location, status, is_connect, warning"
        ).eq("user_id", user_id).order("created_at", desc=True).execute()

        devices = response.data

        return JSONResponse({
            "message": "Lấy danh sách thiết bị thành công",
            "devices": devices
        })

    except Exception as e:
        print("❌ Lỗi khi lấy danh sách thiết bị:", e)
        return JSONResponse({"error": "Không thể lấy danh sách thiết bị"}, status_code=500)


@app.get("/api/me")
async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse({"error": "Thiếu token"}, status_code=401)

    token = authorization.replace("Bearer ", "").strip()
    user_id = decode_token(token)

    if not user_id:
        return JSONResponse({"error": "Token không hợp lệ"}, status_code=403)

    try:
        # Chỉ query user_profiles thôi, không cần đụng auth.users
        result = supabase.table("user_profiles") \
            .select("id, name, email, phone, role, created_at") \
            .eq("id", user_id) \
            .single() \
            .execute()

        return JSONResponse({
            "user": result.data
        })

    except Exception as e:
        print("❌ Lỗi lấy user:", e)
        return JSONResponse({"error": "Lỗi server"}, status_code=500)

# 🔁 Chạy local với port=8765 hoặc Render tự chọn PORT
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="debug",
    )
