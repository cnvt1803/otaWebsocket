from fastapi import Request
from fastapi import Header
from jose import jwt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from supabase import create_client, Client
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import requests
import json
import uvicorn
import os
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Kết nối Supabase
SUPABASE_URL = "https://zkzyawzjmllvqzmedsxd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inprenlhd3pqbWxsdnF6bWVkc3hkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MTQyOTAzNSwiZXhwIjoyMDY3MDA1MDM1fQ.IG8eGax0lUxkUOW8TpJ6M0QvSafB-gM2NWsg6wIOlTU"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()
connected_devices: dict[str, dict[str, WebSocket]] = {}
reconnect_tasks: dict[str, asyncio.Task] = {}


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


@app.post("/api/update-device")
async def update_device_api(request: Request):
    body = await request.json()
    device_id = body.get("device_id")

    res = supabase.table("devices").select(
        "*").eq("device_id", device_id).single().execute()
    if not res.data:
        return JSONResponse({"error": "Thiết bị không tồn tại"}, status_code=404)

    device = res.data
    current_version = device["version"]
    device_name = device["name"]
    user_id = device["user_id"]

    print(f"🚀 Gửi OTA cho {device_id} ({device_name}) thuộc user {user_id}")

    ota = get_latest_ota(device_name, current_version)
    if not ota:
        return JSONResponse({"message": "Thiết bị đã ở phiên bản mới nhất"})

    if user_id in connected_devices and device_id in connected_devices[user_id]:
        ws = connected_devices[user_id][device_id]

        ota_with_device_id = {
            "device_id": device_id,
            **ota
        }

        await ws.send_json(ota_with_device_id)

        supabase.table("devices").update({"status": "waiting"}).eq(
            "device_id", device_id).execute()

        print(f"✅ Đã gửi OTA cho ESP {device_id}")
        return {"message": "Đã gửi OTA", "ota": ota_with_device_id}
    else:
        return JSONResponse({"error": "ESP chưa kết nối"}, status_code=400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    import uvicorn
    uvicorn.run("websocket-userid:app", host="0.0.0.0", port=port, reload=True)
