import asyncio
import websockets
import json
import random
import time

# 🟢 Cấu hình thiết bị giả
USER_ID = "0aa615bb-68a4-4a46-a461-ecd7fa9b1432"
DEVICE_ID = "0aa615bb-68a4-4a46-a461-ecd7fa9b1432_6"
FIRMWARE_VERSION = "1.0.0"

# Địa chỉ WebSocket server
# Thay bằng IP hoặc domain nếu chạy online
WS_URL = f"ws://localhost:8765/ws/{USER_ID}"

# Giả lập quá trình OTA


async def handle_ota(data, websocket):
    print("📥 Nhận OTA từ server:")
    print(json.dumps(data, indent=2, ensure_ascii=False))

    version = data.get("version", "unknown")

    # 🕓 Giả lập thời gian tải firmware
    print(f"⬇️ Đang tải firmware phiên bản {version} ...")
    await asyncio.sleep(2)

    # ✅ Giả lập OTA thành công hoặc thất bại ngẫu nhiên
    success = random.choice([True, True, True, False])  # 75% thành công

    if success:
        print("✅ Đã cập nhật firmware thành công.")
        await websocket.send(json.dumps({
            "command": "UPDATE_FIRMWARE_SUCCESSFULLY",
            "device_id": DEVICE_ID,
            "version": version
        }))
    else:
        print("❌ Cập nhật firmware thất bại.")
        await websocket.send(json.dumps({
            "command": "UPDATE_FIRMWARE_FAILED",
            "device_id": DEVICE_ID,
            "version": version,
            "error_code": "crc_mismatch",
            "reason": "Checksum không khớp khi ghi flash"
        }))


async def fake_esp():
    try:
        async with websockets.connect(WS_URL) as websocket:
            print(f"🔌 Kết nối tới WebSocket: {WS_URL}")

            # Gửi lệnh REGISTER_DEVICE
            await websocket.send(json.dumps({
                "command": "REGISTER_DEVICE",
                "device_id": DEVICE_ID,
                "version": FIRMWARE_VERSION
            }))

            # Chờ các thông điệp từ server
            while True:
                message = await websocket.recv()
                print(f"\n📨 Nhận từ server:\n{message}")

                try:
                    data = json.loads(message)
                    command = data.get("command")

                    if command == "UPDATE_FIRMWARE":
                        await handle_ota(data, websocket)

                    elif command == "ACK_SUCCESS":
                        print("🎉 Server xác nhận cập nhật thành công.")

                    elif command == "ACK_FAILED":
                        print("⚠️ Server xác nhận cập nhật thất bại.")

                    else:
                        print("⚠️ Lệnh không xác định từ server:", command)

                except Exception as e:
                    print("❌ Lỗi xử lý message:", e)

    except Exception as e:
        print("❌ Không thể kết nối tới WebSocket:", e)

if __name__ == "__main__":
    asyncio.run(fake_esp())
