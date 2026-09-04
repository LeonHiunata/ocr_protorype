import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.environ.get('GEMINI_API_KEY')

url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={API_KEY}"
payload = {
    "contents": [{"parts": [{"text": "test"}]}],
    "generationConfig": {
        "temperature": 0.0,
        "response_mime_type": "application/json"
    }
}

resp = requests.post(url, json=payload)
print("--- HEADERS ---")
for k, v in resp.headers.items():
    print(f"{k}: {v}")

print("--- JSON RESPONSE ---")
print(json.dumps(resp.json(), indent=2))
