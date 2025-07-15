import requests
import json

API_URL = "http://localhost:8765/api/update-device-version"

DEVICE_IDS = ["0aa615bb-68a4-4a46-a461-ecd7fa9b1432_6"]
VERSION = "1.1.5"


def request_ota_update(device_ids, version):
    payload = {
        "device_ids": device_ids,
        "version": version
    }

    try:
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()

        data = response.json()
        print("📦 Phản hồi từ server:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

    except requests.exceptions.RequestException as e:
        print("❌ Lỗi khi gửi yêu cầu OTA:", e)


if __name__ == "__main__":
    request_ota_update(DEVICE_IDS, VERSION)
