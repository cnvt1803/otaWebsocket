import asyncio
import websockets
import json

DEVICE_ID = "esp001"
# WS_ENDPOINT = "wss://otawebsocket.onrender.com/ws"  # ✅ nếu chạy trên Render
WS_ENDPOINT = "ws://localhost:8765/ws"  # ✅ nếu chạy local


async def fake_esp():
    try:
        async with websockets.connect(WS_ENDPOINT) as websocket:
            # 🔐 Đăng ký thiết bị với server
            await websocket.send(json.dumps({
                "action": "register_esp",
                "device_id": DEVICE_ID
            }))
            print(f"🔌 ESP {DEVICE_ID} đã kết nối đến server...")

            while True:
                try:
                    message = await websocket.recv()
                    print("📨 Nhận raw message từ server:", message)
                    data = json.loads(message)

                    # ✅ Kiểm tra xem đây có phải bản OTA không
                    if "version" in data and "url" in data:
                        print(
                            f"📥 OTA mới: v{data['version']}, tải từ: {data['url']}")
                        await asyncio.sleep(2)  # giả lập thời gian tải

                        # ✅ Gửi lại báo cáo OTA thành công
                        await websocket.send(json.dumps({
                            "action": "ota_done",
                            "device_id": DEVICE_ID,
                            "version": data["version"]
                        }))
                        print("✅ OTA hoàn tất, đã báo server.")

                    elif data.get("message"):
                        print("🎉 Server xác nhận:", data["message"])

                    else:
                        print("❓ Phản hồi không xác định:", data)

                except websockets.exceptions.ConnectionClosed:
                    print("🔌 ESP mất kết nối với server")
                    break

    except ConnectionRefusedError:
        print("❌ Không kết nối được server! Kiểm tra server có đang chạy không?")
    except Exception as e:
        print("⚠️ Lỗi không xác định:", e)

# 🧪 Chạy mô phỏng ESP
if __name__ == "__main__":
    asyncio.run(fake_esp())
