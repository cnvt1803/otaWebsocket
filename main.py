from fastapi.responses import JSONResponse
from fastapi import Query
from fastapi.responses import PlainTextResponse, JSONResponse
from jose import jwt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, Request
from fastapi import UploadFile, File, Form, Query
from supabase import create_client, Client
from fastapi.middleware.cors import CORSMiddleware
from datetime import date
import httpx
import requests
import json
import uvicorn
import os
import asyncio
import traceback
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
SUPABASE_JWT_SECRET = "koJJ0d58iKJYPdhEZhBIBKLEXno9HRWgE6eCC7SVsd/HrbcPfSsxgvppGthK0ciLIBM+RSUSLSnjttsQ+wJ2sA=="
SUPABASE_BUCKET = "ota"
SUPABASE_FOLDER = "ota_muti"
PUBLIC_BASE = f"https://zkzyawzjmllvqzmedsxd.storage.supabase.co/v1/object/public/{SUPABASE_BUCKET}/{SUPABASE_FOLDER}"
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

                    update_data = {"is_connect": "online"}

                    if "version" in data:
                        version = data["version"]
                        update_data["version"] = version
                        print(f"📌 Phiên bản firmware: {version}")

                    supabase.table("devices").update(update_data).eq(
                        "device_id", device_id).execute()

                elif command == "UPDATE_FIRMWARE_APPROVE":
                    print(
                        f"ESP {device_id} bắt đầu cập nhật: v{data.get('version')}", flush=True)

                elif command == "UPDATE_FIRMWARE_SUCCESSFULLY":
                    new_version = data.get("version")
                    print(
                        f"ESP {device_id} cập nhật thành công v{new_version}", flush=True)
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
                        f"ESP {device_id} cập nhật v{failed_version} thất bại", flush=True)
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
                    version = data.get("version", "unknown")

                    insert_result = supabase.table("devices").insert({
                        "user_id": user_id,
                        "version": version,
                        "status": "new_divice",
                        "is_connect": "online"
                    }).execute()

                    if insert_result.data and len(insert_result.data) > 0:
                        device_id = insert_result.data[0]["device_id"]

                        if user_id not in connected_devices:
                            connected_devices[user_id] = {}
                        connected_devices[user_id][device_id] = websocket

                        print(
                            f"Đã tạo và kết nối thiết bị mới: {device_id} cho user {user_id}", flush=True)
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


@app.post("/api/update-device")
async def update_device_api(request: Request):
    body = await request.json()
    device_ids = body.get("device_ids")

    if not device_ids or not isinstance(device_ids, list):
        return JSONResponse({"error": "Vui lòng cung cấp danh sách device_ids"}, status_code=400)

    results = []

    for device_id in device_ids:
        try:
            res = supabase.table("devices").select(
                "*").eq("device_id", device_id).single().execute()
            if not res.data:
                results.append(
                    {"device_id": device_id, "status": "Không tồn tại"})
                continue

            device = res.data
            current_version = device["version"]
            device_name = device["name"]
            user_id = device["user_id"]

            # 🔒 Nếu thiết bị chưa có tên, không cho update OTA
            if not device_name or device_name.strip() == "":
                results.append({
                    "device_id": device_id,
                    "status": "Thiết bị chưa đặt tên. Vui lòng đặt tên trước khi cập nhật"
                })
                continue

            print(f"🚀 Xử lý OTA cho {device_id} ({device_name})")

            ota = get_latest_ota(device_name, current_version)
            if not ota:
                results.append({
                    "device_id": device_id,
                    "status": "✅ Đã ở phiên bản mới nhất"
                })
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
                results.append({
                    "device_id": device_id,
                    "status": "✅ Đã gửi OTA"
                })
            else:
                results.append({
                    "device_id": device_id,
                    "status": "⚠️ ESP chưa kết nối"
                })

        except Exception as e:
            print(f"❌ Lỗi khi xử lý {device_id}: {e}")
            results.append({
                "device_id": device_id,
                "status": f"❌ Lỗi: {str(e)}"
            })

    return {"results": results}


def get_ota_by_version(device_name, version):
    if not version.startswith("v"):
        version = f"v{version}"

    ota_url = f"{PUBLIC_BASE}/{device_name}/{version}/ota.json"
    try:
        resp = httpx.get(ota_url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"❌ Không tìm thấy OTA {version}: {resp.status_code}")
            return None
    except Exception as e:
        print(f"❌ Lỗi khi tải OTA {version}: {e}")
        return None


@app.post("/api/update-device-version")
async def update_device_api(request: Request):
    body = await request.json()
    device_ids = body.get("device_ids")
    version = body.get("version")  # Thêm version từ body

    if not device_ids or not isinstance(device_ids, list):
        return JSONResponse({"error": "Vui lòng cung cấp danh sách device_ids"}, status_code=400)
    if not version:
        return JSONResponse({"error": "Vui lòng cung cấp version"}, status_code=400)

    results = []

    for device_id in device_ids:
        try:
            res = supabase.table("devices").select(
                "*").eq("device_id", device_id).single().execute()
            if not res.data:
                results.append(
                    {"device_id": device_id, "status": "Không tồn tại"})
                continue

            device = res.data
            device_name = device["name"]
            user_id = device["user_id"]

            if not device_name or device_name.strip() == "":
                results.append({
                    "device_id": device_id,
                    "status": "Thiết bị chưa đặt tên. Vui lòng đặt tên trước khi cập nhật"
                })
                continue

            print(f"🚀 Xử lý OTA {version} cho {device_id} ({device_name})")

            ota = get_ota_by_version(device_name, version)
            if not ota:
                results.append({
                    "device_id": device_id,
                    "status": f"❌ Không tìm thấy OTA version {version} cho thiết bị '{device_name}'"
                })
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

                print(f"✅ Gửi OTA {version} thành công cho ESP {device_id}")
                results.append({
                    "device_id": device_id,
                    "status": f"✅ Đã gửi OTA version {version}"
                })
            else:
                results.append({
                    "device_id": device_id,
                    "status": "⚠️ ESP chưa kết nối"
                })

        except Exception as e:
            print(f"❌ Lỗi khi xử lý {device_id}: {e}")
            results.append({
                "device_id": device_id,
                "status": f"❌ Lỗi: {str(e)}"
            })

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
        # 📌 Kiểm tra email đã có trong bảng user_profiles
        check = supabase.table("user_profiles") \
            .select("email") \
            .eq("email", email) \
            .execute()

        if check.data and len(check.data) > 0:
            return JSONResponse({
                "error": "Email đã được đăng ký"
            }, status_code=409)  # 409 Conflict

        # 📩 Gửi POST tới Supabase Auth API để tạo tài khoản
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

        # ✅ Nếu email đã tồn tại trong Auth
        if response.status_code == 422:
            error_data = response.json()
            if error_data.get("error_code") == "email_exists":
                return JSONResponse({
                    "message": "Email đã được đăng ký trong hệ thống"
                }, status_code=409)

        # ❌ Các lỗi khác
        if response.status_code >= 300:
            return JSONResponse({"message": response.json()}, status_code=response.status_code)

        # 🆔 Lấy user_id từ Auth để lưu vào bảng user_profiles
        user_id = response.json()["id"]

        # 💾 Insert vào bảng user_profiles
        supabase.table("user_profiles").insert({
            "id": user_id,
            "role": role,
            "name": name,
            "email": email,
            "phone": phone
        }).execute()

        return JSONResponse({
            "message": "✅ Tạo tài khoản thành công",
            "user_id": user_id
        })

    except Exception as e:
        print("❌ Lỗi tạo tài khoản:", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/forgot-password")
async def forgot_password(request: Request):
    body = await request.json()
    email = body.get("email")

    if not email:
        return JSONResponse({"error": "Vui lòng nhập email"}, status_code=400)

    try:
        url = f"{SUPABASE_URL}/auth/v1/recover"
        headers = {
            "apikey": SUPABASE_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "email": email
        }

        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            return JSONResponse({"message": "📩 Email khôi phục mật khẩu đã được gửi."})
        else:
            return JSONResponse({"error": response.json()}, status_code=response.status_code)

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


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


@app.post("/api/upload-firmware")
async def upload_firmware(
    device_name: str = Form(...),
    version: str = Form(...),
    changelog: str = Form(None),
    file: UploadFile = File(...)
):
    try:
        # ✅ Chuẩn hóa version
        if not version.startswith("v"):
            version = f"v{version}"

        # ✅ Đường dẫn Supabase
        folder_path = f"{SUPABASE_FOLDER}/{device_name}/{version}"
        firmware_path = f"{folder_path}/firmware.bin"
        latest_json_path = f"{SUPABASE_FOLDER}/{device_name}/ota-latest.json"
        version_json_path = f"{folder_path}/ota.json"

        async with httpx.AsyncClient() as client:
            # ✅ Đọc file
            firmware_bytes = await file.read()

            # ✅ Upload firmware.bin (ghi đè)
            resp = await client.put(
                f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{firmware_path}",
                content=firmware_bytes,
                headers={
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/octet-stream"
                },
                params={"upsert": "true"}
            )
            if resp.status_code >= 400:
                return JSONResponse({
                    "error": "❌ Upload firmware thất bại",
                    "detail": resp.text
                }, status_code=500)

            # ✅ Tạo nội dung ota JSON
            file_size = round(len(firmware_bytes) / (1024 * 1024), 2)
            today = str(date.today())
            public_url = f"{PUBLIC_BASE}/{device_name}/{version}/firmware.bin"
            ota = {
                "version": version.replace("v", ""),
                "file": "firmware.bin",
                "url": public_url,
                "size": str(file_size),
                "released": today
            }
            ota_bytes = json.dumps(ota, indent=2).encode("utf-8")

            # ✅ Upload ota-latest.json
            latest_resp = await client.put(
                f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{latest_json_path}",
                content=ota_bytes,
                headers={
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json"
                },
                params={"upsert": "true"}
            )
            if latest_resp.status_code >= 400:
                return JSONResponse({
                    "error": "❌ Lỗi ghi ota-latest.json",
                    "detail": latest_resp.text
                }, status_code=500)

            # ✅ Upload ota.json trong thư mục version
            version_resp = await client.post(
                f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{version_json_path}",
                content=ota_bytes,
                headers={
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json"
                },
                params={"upsert": "true"}
            )
            if version_resp.status_code >= 400:
                return JSONResponse({
                    "error": "❌ Firmware và ota-latest ok, nhưng lỗi khi ghi ota.json",
                    "detail": version_resp.text
                }, status_code=500)

        # 1. Đánh dấu các bản trước đó là is_latest = false
        supabase.table("firmware_versions") \
            .update({"is_latest": False}) \
            .eq("device_name", device_name) \
            .execute()

        # 2. Thêm bản mới
        supabase.table("firmware_versions").insert({
            "device_name": device_name,
            "version": version.replace("v", ""),
            "changelog": changelog or "",
            "file_url": public_url,
            "is_latest": True,
        }).execute()

        return {
            "message": f"✅ Đã upload firmware {version} cho thiết bị '{device_name}'",
            "firmware_url": public_url,
            "ota_info": ota
        }

    except Exception as e:
        traceback.print_exc()
        return JSONResponse({
            "error": "🔥 Server exception",
            "detail": str(e)
        }, status_code=500)


@app.get("/api/list-versions")
async def get_all_firmware_versions():
    try:
        res = supabase.table("firmware_versions") \
            .select("device_name, version, changelog, release_date, file_url, is_latest, created_at") \
            .order("device_name", desc=False) \
            .order("release_date", desc=True) \
            .execute()

        if not res.data:
            return JSONResponse({"message": "Không có dữ liệu firmware"}, status_code=404)

        grouped = {}
        for item in res.data:
            name = item["device_name"]
            if name not in grouped:
                grouped[name] = []
            grouped[name].append(item)

        return grouped

    except Exception as e:
        print("❌ Lỗi khi lấy tất cả firmware:", e)
        return JSONResponse({"error": "Lỗi server", "detail": str(e)}, status_code=500)


@app.delete("/api/delete-version")
async def delete_version(device_name: str = Query(...), version: str = Query(...)):
    version_folder = f"v{version}"  # vd: v1.2.1
    # vd: ota_muti/dataloger/v1.2.1
    base_path = f"{SUPABASE_FOLDER}/{device_name}/{version_folder}"

    # Các file cần xoá
    firmware_path = f"{base_path}/firmware.bin"
    ota_json_path = f"{base_path}/ota.json"

    try:
        async with httpx.AsyncClient() as client:
            for file_path in [firmware_path, ota_json_path]:
                resp = await client.delete(
                    f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{file_path}",
                    headers={"Authorization": f"Bearer {SUPABASE_KEY}"}
                )
                if resp.status_code >= 300:
                    print(f"⚠️ Không xoá được {file_path}: {resp.text}")
                    return JSONResponse({
                        "error": f"❌ Không xoá được {file_path}",
                        "detail": resp.text
                    }, status_code=500)

        # ✅ Sau khi xoá file, xoá bản ghi trong bảng firmware_versions
        supabase.table("firmware_versions") \
            .delete() \
            .eq("device_name", device_name) \
            .eq("version", version) \
            .execute()

        return {
            "message": f"✅ Đã xoá version '{version}' và các file firmware của thiết bị '{device_name}'"
        }

    except Exception as e:
        print("❌ Lỗi khi xoá file OTA:", e)
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="debug",
    )
