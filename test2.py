import asyncio
import websockets
import json
from datetime import datetime
import random

DEVICE_ID = "006"
DEVICE_VERSION = "1.0.0"
WS_ENDPOINT = "ws://localhost:8765/ws"
SIMULATE_FAIL = True  # Đặt False nếu muốn test OTA thành công


async def send_ping(websocket):
    while True:
        await asyncio.sleep(20)
        ping = {
            "command": "PING",
            "device_id": DEVICE_ID
        }
        print("📡 Gửi ping:", ping)
        await websocket.send(json.dumps(ping))


async def send_log(websocket):
    while True:
        await asyncio.sleep(60)
        log_data = {
            "command": "LOG",
            "device_id": DEVICE_ID,
            "timestamp": datetime.now().isoformat(),
            "message": "Thiết bị hoạt động bình thường."
        }
        print("📝 Gửi log:", log_data)
        await websocket.send(json.dumps(log_data))

# ==================================
# 🔁 Phản hồi khi nhận UPDATE_FIRMWARE
# ==================================


async def respond_ota(websocket, version, url):
    print(f"🚀 Nhận yêu cầu OTA: v{version} từ {url}")

    # Gửi APPROVE trước khi cập nhật
    await websocket.send(json.dumps({
        "command": "UPDATE_FIRMWARE_APPROVE",
        "device_id": DEVICE_ID,
        "version": version
    }))
    print("📦 Bắt đầu cập nhật...")

    await asyncio.sleep(3)

    if SIMULATE_FAIL:
        # Giả lập lỗi OTA
        error_list = [
            ("FLASH_ERROR", "Không thể ghi vào bộ nhớ flash."),
            ("CHECKSUM_FAIL", "Sai mã kiểm tra checksum."),
            ("NETWORK_LOSS", "Mất kết nối trong lúc cập nhật."),
            ("DISK_FULL", "Không đủ bộ nhớ để ghi firmware.")
        ]
        error_code, reason = random.choice(error_list)

        await websocket.send(json.dumps({
            "command": "UPDATE_FIRMWARE_FAILED",
            "device_id": DEVICE_ID,
            "version": version,
            "error_code": error_code,
            "reason": reason
        }))
        print(f"❌ OTA thất bại: [{error_code}] - {reason}")
    else:
        # OTA thành công
        await websocket.send(json.dumps({
            "command": "UPDATE_FIRMWARE_SUCCESSFULLY",
            "device_id": DEVICE_ID,
            "version": version
        }))
        print("✅ OTA thành công.")


async def fake_esp():
    try:
        async with websockets.connect(WS_ENDPOINT) as websocket:
            # Gửi REGISTER_DEVICE
            await websocket.send(json.dumps({
                "command": "REGISTER_DEVICE",
                "device_id": DEVICE_ID,
                "version": DEVICE_VERSION
            }))
            print(
                f"🔌 ESP {DEVICE_ID} đã kết nối với firmware v{DEVICE_VERSION}")

            asyncio.create_task(send_ping(websocket))
            asyncio.create_task(send_log(websocket))

            # Nhận lệnh từ server
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
                        print("📬 Server xác nhận cập nhật thành công.")
                    elif command == "ACK_FAILED":
                        print("⚠️ Server báo lỗi OTA:", data.get("reason"))
                    else:
                        print("❓ Lệnh không xác định:", command)

                except websockets.exceptions.ConnectionClosed:
                    print("❌ Mất kết nối với server.")
                    break

    except ConnectionRefusedError:
        print("🚫 Không thể kết nối đến WebSocket server.")
    except Exception as e:
        print("💥 Lỗi không xác định:", e)

if __name__ == "__main__":
    asyncio.run(fake_esp())
