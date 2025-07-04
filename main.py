from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from supabase import create_client, Client
from fastapi.middleware.cors import CORSMiddleware
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

    res = supabase.table("devices").select(
        "*").eq("device_id", device_id).execute()
    if not res.data:
        return JSONResponse({"error": "Thiết bị không tồn tại"}, status_code=404)

    device = res.data[0]
    current_version = device["version"]
    device_name = device["name"]

    print(f"📤 Gửi OTA cho {device_id} ({device_name})...")

    ota = get_latest_ota(device_name, current_version)
    if not ota:
        return JSONResponse({"message": "Thiết bị đã ở phiên bản mới nhất"})

    if device_id in connected_devices:
        ws = connected_devices[device_id]

        # ⚠️ SỬA LẠI: send_json thay vì send(json.dumps)
        await ws.send_json({
            "action": "ota_update",
            "ota": ota
        })

        # Cập nhật trạng thái sang "waiting"
        supabase.table("devices").update({"status": "waiting"}).eq(
            "device_id", device_id).execute()

        print(f"📤 Đã gửi OTA cho ESP {device_id}")
        return {"message": "Đã gửi OTA", "ota": ota}

    else:
        return JSONResponse({"error": "ESP chưa kết nối"}, status_code=400)

# ✅ Chạy server

# 🔁 Chạy local với port=8765 hoặc Render tự chọn PORT
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
