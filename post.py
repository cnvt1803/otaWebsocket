# import requests

# url = "http://localhost:8765/api/update-device"

# payload = {
#     "device_id": "006"
# }

# response = requests.post(url, json=payload)

# print("✅ Status Code:", response.status_code)
# print("📦 Response:", response.json())

import requests
import json

# Địa chỉ API của server bạn (thay bằng domain hoặc IP thật)
API_URL = "http://localhost:8765/api/update-device"

# ID của thiết bị ESP cần update
DEVICE_ID = "002"


def request_ota_update(device_id):
    payload = {
        "device_id": device_id
    }

    try:
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()  # raise lỗi nếu HTTP status >= 400

        data = response.json()
        print("📦 Phản hồi từ server:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

    except requests.exceptions.RequestException as e:
        print("❌ Lỗi khi gửi yêu cầu OTA:", e)


if __name__ == "__main__":
    request_ota_update(DEVICE_ID)
