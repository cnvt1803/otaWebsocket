import requests

url = "http://localhost:8765/api/update-device"

payload = {
    "device_id": "002"
}

response = requests.post(url, json=payload)

print("✅ Status Code:", response.status_code)
print("📦 Response:", response.json())
