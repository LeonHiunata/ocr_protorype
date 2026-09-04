import os
import json

# Navigate from backend/core/ to backend/data/
HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "data_history.json")

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to read history file: {e}")
        return []

def save_history(data):
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[WARN] Failed to save history file: {e}")
