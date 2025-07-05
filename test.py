import asyncio
import websockets
import json
from datetime import datetime
import random

DEVICE_ID = "002"
# WS_ENDPOINT = "ws://localhost:8765/ws"
WS_ENDPOINT = "wss://otawebsocket.onrender.com/ws"

# 🔁 Task gửi ping mỗi 5s


async def send_ping(websocket):
    while True:
        await asyncio.sleep(20)
        msg = {
            "action": "ping",
            "device_id": DEVICE_ID
        }
        print("📤 Gửi ping:", msg)  # 👈 thêm dòng này
        await websocket.send(json.dumps(msg))


# 🧠 Task gửi log giả lập mỗi 10s


async def send_fake_log(websocket):
    while True:
        await asyncio.sleep(20)
        fake_data = {
            "action": "log",
            "device_id": DEVICE_ID,
            "timestamp": datetime.now().isoformat(),
            "temperature": round(random.uniform(25, 35), 2),
            "humidity": round(random.uniform(40, 60), 2)
        }
        await websocket.send(json.dumps(fake_data))
        print("📝 Gửi log:", fake_data)

# 🧠 Task chính (nhận dữ liệu từ server)


async def fake_esp():
    try:
        async with websockets.connect(WS_ENDPOINT) as websocket:
            # Đăng ký thiết bị với server
            await websocket.send(json.dumps({
                "action": "register_esp",
                "device_id": DEVICE_ID
            }))
            print(f"🔌 ESP {DEVICE_ID} đã kết nối đến server...")

            # 🎯 Chạy song song 2 task gửi dữ liệu
            asyncio.create_task(send_ping(websocket))
            asyncio.create_task(send_fake_log(websocket))

            while True:
                try:
                    message = await websocket.recv()
                    print("📩 Nhận từ server:", message)
                    data = json.loads(message)

                    # Nhận OTA từ server
                    if "version" in data and "url" in data:
                        print(
                            f"🚀 OTA mới: v{data['version']}, tải từ: {data['url']}")
                        await asyncio.sleep(2)  # Giả lập delay tải firmware
                        await websocket.send(json.dumps({
                            "action": "ota_done",
                            "device_id": DEVICE_ID,
                            "version": data["version"]
                        }))
                        print("✅ OTA hoàn tất, đã báo server.")

                    elif data.get("message"):
                        print("📬 Server phản hồi:", data["message"])

                    else:
                        print("❓ Phản hồi không xác định:", data)

                except websockets.exceptions.ConnectionClosed:
                    print("❌ ESP mất kết nối với server")
                    break

    except ConnectionRefusedError:
        print("❌ Không kết nối được server! Kiểm tra lại.")
    except Exception as e:
        print("⚠️ Lỗi không xác định:", e)


if __name__ == "__main__":
    asyncio.run(fake_esp())
