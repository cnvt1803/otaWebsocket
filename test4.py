import asyncio
import websockets
import json

# ✅ Thông tin user_id bạn muốn test (thay bằng user_id của bạn trong Supabase)
USER_ID = "0aa615bb-68a4-4a46-a461-ecd7fa9b1432"

# ✅ Tên thiết bị và vị trí để đăng ký


async def fake_esp():
    uri = f"ws://localhost:8765/ws/{USER_ID}"

    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Đã kết nối WebSocket")

            # 📦 Gửi lệnh tạo thiết bị mới
            await websocket.send(json.dumps({
                "command": "REGISTER_NEW_DEVICE",
                "version": "1.0.0"  # Bạn có thể thay đổi phiên bản nếu cần
            }))

            # ⏳ Chờ phản hồi từ server
            while True:
                response = await websocket.recv()
                data = json.loads(response)

                if data.get("command") == "ACK_NEW_DEVICE":
                    print(f"🎉 Thiết bị mới được tạo thành công:")
                    print(f"    👉 device_id = {data['device_id']}")

                elif data.get("command") == "ACK_FAILED":
                    print(f"❌ Tạo thiết bị thất bại: {data.get('message')}")

                else:
                    print(f"🔔 Nhận lệnh khác từ server: {data}")

    except Exception as e:
        print("❌ Không thể kết nối tới WebSocket:", e)


if __name__ == "__main__":
    asyncio.run(fake_esp())
