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

connected_devices: dict[str, WebSocket] = {}


def get_latest_ota(device_name, current_version):
    path = f"ota_muti/{device_name}/ota-latest.json"
    try:
        file = supabase.storage.from_("ota").download(path)
        ota = json.loads(file.decode("utf-8"))
        if ota["version"] != current_version:
            return ota
    except Exception as e:
        print(" OTA fetch error:", e)
    return None


def update_device(device_id, version):
    supabase.table("devices") \
        .update({"version": version, "status": "done"}) \
        .eq("device_id", device_id) \
        .execute()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    print("WebSocket /ws đã được gọi")
    await websocket.accept()
    device_id = None

    try:
        while True:
            print("🕓 Chờ tin nhắn từ ESP...")
            message = await websocket.receive_text()
            print(f"📩 Nhận từ ESP: {message}")

            try:
                data = json.loads(message)
                command = data.get("command")
                device_id = data.get("device_id")

                if command == "REGISTER_DEVICE":
                    connected_devices[device_id] = websocket
                    print(f"✅ ESP {device_id} đã kết nối")

                    print("📚 Danh sách thiết bị đang kết nối:",
                          list(connected_devices.keys()))

                    # 🟢 Tạo payload update
                    update_data = {"is_connect": "online"}

                    if "version" in data:
                        version = data["version"]
                        update_data["version"] = version
                        print(f"📌 Phiên bản firmware: {version}")
                    else:
                        print(
                            "⚠️ ESP không gửi version, giữ nguyên version hiện tại.")

                    # 🔄 Cập nhật lên Supabase
                    supabase.table("devices").update(update_data).eq(
                        "device_id", device_id).execute()

                elif command == "UPDATE_FIRMWARE_APPROVE":
                    print(
                        f"📦 ESP {device_id} đang bắt đầu cập nhật: v{data.get('version')}")

                elif command == "UPDATE_FIRMWARE_SUCCESSFULLY":
                    new_version = data.get("version")
                    print(
                        f"🎉 ESP {device_id} đã cập nhật thành công lên v{new_version}")
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
                        f"⚠️ ESP {device_id} cập nhật version {failed_version} thất bại"
                    )
                    print(f"❌ Lỗi cập nhật: [{error_code}] - {reason}")

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

                elif command == "LOG":
                    print(f"Log từ {device_id}: {data}")

                else:
                    print(f"Lệnh không xác định: {command}")

            except Exception as e:
                print(" Lỗi xử lý frame:", e)

    except WebSocketDisconnect:
        print(f"🔴 ESP {device_id} ngắt kết nối")
        if device_id in connected_devices:
            del connected_devices[device_id]
         # 🔴 Cập nhật trạng thái offline
    if device_id:
        supabase.table("devices").update({"is_connect": "offline"}).eq(
            "device_id", device_id).execute()


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

    print(f" Gửi OTA cho {device_id} ({device_name})...")

    ota = get_latest_ota(device_name, current_version)
    if not ota:
        return JSONResponse({"message": "Thiết bị đã ở phiên bản mới nhất"})

    if device_id in connected_devices:
        ws = connected_devices[device_id]
        ota_with_device_id = {
            "device_id": f"{device_name}_{user_id}_{device_id}",
            **ota
        }

        await ws.send_json(ota_with_device_id)

        supabase.table("devices").update({"status": "waiting"}).eq(
            "device_id", device_id).execute()

        print(f"Đã gửi OTA cho ESP {device_id}")
        return {"message": "Đã gửi OTA", "ota": ota_with_device_id}
    else:
        return JSONResponse({"error": "ESP chưa kết nối"}, status_code=400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    uvicorn.run("websocket:app", host="0.0.0.0", port=port, reload=True)
