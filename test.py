import asyncio
import websockets
import json
from datetime import datetime

DEVICE_ID = "002"
DEVICE_VERSION = "1.0.2"
WS_ENDPOINT = "ws://localhost:8765/ws"
# WS_ENDPOINT = "wss://otawebsocket.onrender.com/ws"


async def send_ping(websocket):
    while True:
        await asyncio.sleep(20)
        msg = {
            "command": "PING",
            "device_id": DEVICE_ID
        }
        print("Gửi ping:", msg)
        await websocket.send(json.dumps(msg))

# 📝 Gửi log định kỳ


async def send_fake_log(websocket):
    while True:
        await asyncio.sleep(60)
        fake_data = {
            "command": "LOG",
            "device_id": DEVICE_ID,
            "timestamp": datetime.now().isoformat(),
        }
        await websocket.send(json.dumps(fake_data))
        print("Gửi log:", fake_data)


async def respond_ota(websocket, version, url):
    print(f"🚀 Nhận yêu cầu OTA: v{version}, url: {url}")
    await asyncio.sleep(20)
    await websocket.send(json.dumps({
        "command": "UPDATE_FIRMWARE_APPROVE",
        "device_id": DEVICE_ID,
        "version": version,
        "url": url
    }))
    print("📥 Đang cập nhật firmware...")

    await asyncio.sleep(3)

    await websocket.send(json.dumps({
        "command": "UPDATE_FIRMWARE_SUCCESSFULLY",
        "device_id": DEVICE_ID,
        "version": version,
        "url": url
    }))
    print("✅ Đã cập nhật thành công.")

# 🔌 Thiết bị giả lập


async def fake_esp():
    try:
        async with websockets.connect(WS_ENDPOINT) as websocket:
            # Gửi frame REGISTER_DEVICE
            await websocket.send(json.dumps({
                "command": "REGISTER_DEVICE",
                "device_id": DEVICE_ID,
                "version": DEVICE_VERSION
            }))
            print(f"🔌 Thiết bị {DEVICE_ID} đã kết nối...")

            # Gửi ping và log song song
            asyncio.create_task(send_ping(websocket))
            asyncio.create_task(send_fake_log(websocket))

            while True:
                try:
                    message = await websocket.recv()
                    print("📩 Nhận từ server:", message)
                    data = json.loads(message)

                    command = data.get("command")
                    if command == "UPDATE_FIRMWARE":
                        await respond_ota(
                            websocket,
                            data.get("version"),
                            data.get("url")
                        )
                    elif command == "ACK_SUCCESS":
                        print("📬 Server xác nhận OTA thành công.")
                    elif command == "ACK_FAILED":
                        print("⚠️ Server báo không cần cập nhật.")
                    else:
                        print("❓ Phản hồi không xác định:", data)

                except websockets.exceptions.ConnectionClosed:
                    print("❌ Mất kết nối với server.")
                    break

    except ConnectionRefusedError:
        print("Không kết nối được server.")
    except Exception as e:
        print("Lỗi không xác định:", e)

if __name__ == "__main__":
    asyncio.run(fake_esp())
