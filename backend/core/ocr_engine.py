# =============================================================================
# ocr_engine.py  –  Container OCR Service (Gemini Vision API)
# =============================================================================
import os
import cv2
import time
import json
import base64
import requests
import numpy as np
import datetime

try:
    from dotenv import load_dotenv
    # Load .env from the root directory
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except ImportError:
    pass

# ── Configuration (override via env variables) ────────────────────────────────
DEBUG_MODE        = os.environ.get('OCR_DEBUG', 'true').lower() in ('1', 'true', 'yes')
MAX_IMAGE_DIM     = int(os.environ.get('MAX_IMAGE_LONG_SIDE', '1280'))
TIMEOUT_SECONDS   = float(os.environ.get('OCR_TIMEOUT', '45.0'))
GEMINI_API_KEY    = os.environ.get('GEMINI_API_KEY', '')

DEBUG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'debug_outputs')
if DEBUG_MODE:
    os.makedirs(DEBUG_DIR, exist_ok=True)

FIXED_PREFIX = "SPNU"

# ── Logging helpers ──────────────────────────────────────────────────────────
def _log(msg: str):
    if DEBUG_MODE:
        print(f'[OCR] {msg}')

def _save_debug(img, step_name: str):
    if not DEBUG_MODE:
        return
    ts = int(time.time() * 1000)
    path = os.path.join(DEBUG_DIR, f'{ts}_{step_name}.jpg')
    cv2.imwrite(path, img)
    _log(f'Debug image saved: {path}')

# ─────────────────────────────────────────────────────────────────────────────
# ISO 6346 Validation
# ─────────────────────────────────────────────────────────────────────────────
_ISO_CHAR_MAP = {
    'A': 10, 'B': 12, 'C': 13, 'D': 14, 'E': 15, 'F': 16, 'G': 17, 'H': 18,
    'I': 19, 'J': 20, 'K': 21, 'L': 23, 'M': 24, 'N': 25, 'O': 26, 'P': 27,
    'Q': 28, 'R': 29, 'S': 30, 'T': 31, 'U': 32, 'V': 34, 'W': 35, 'X': 36,
    'Y': 37, 'Z': 38,
}

def calculate_check_digit(ten_chars: str) -> str:
    if len(ten_chars) != 10:
        return '?'
    total = 0
    for i, ch in enumerate(ten_chars.upper()):
        if i < 4:
            val = _ISO_CHAR_MAP.get(ch, 0)
        else:
            if not ch.isdigit():
                return '?'
            val = int(ch)
        total += val * (2 ** i)
    result = total % 11
    return str(0 if result == 10 else result)

def validate_iso6346(digits: str):
    """
    Validate ISO 6346 for exactly 7 digits with fixed SPNU prefix.
    """
    if len(digits) != 7 or not digits.isdigit():
        return False, '?'
    
    full_str = FIXED_PREFIX + digits
    expected = calculate_check_digit(full_str[:10])
    if expected == '?':
        return False, '?'
    return (full_str[10] == expected), expected

# ─────────────────────────────────────────────────────────────────────────────
# API Usage Tracking
# ─────────────────────────────────────────────────────────────────────────────
MAX_RPM = int(os.environ.get('GEMINI_MAX_RPM', '15'))
MAX_TPM = int(os.environ.get('GEMINI_MAX_TPM', '1000000'))
MAX_RPD = int(os.environ.get('GEMINI_MAX_RPD', '1500'))

class RateTracker:
    def __init__(self):
        self.requests_today = 0
        self.requests_this_minute = 0
        self.tokens_this_minute = 0
        now = datetime.datetime.now()
        self.current_minute = now.minute
        self.current_day = now.day

    def add_usage(self, tokens_used):
        now = datetime.datetime.now()
        
        if now.day != self.current_day:
            self.requests_today = 0
            self.current_day = now.day
            
        if now.minute != self.current_minute:
            self.requests_this_minute = 0
            self.tokens_this_minute = 0
            self.current_minute = now.minute

        self.requests_today += 1
        self.requests_this_minute += 1
        self.tokens_this_minute += tokens_used

        remaining_rpd = max(0, MAX_RPD - self.requests_today)
        remaining_rpm = max(0, MAX_RPM - self.requests_this_minute)
        remaining_tpm = max(0, MAX_TPM - self.tokens_this_minute)
        
        print("\n" + "="*50)
        print("📊 [GEMINI API USAGE TRACKER]")
        print(f"🔹 Token Dipakai (Request Ini) : {tokens_used}")
        print(f"🔹 Sisa Request (Menit Ini)  : {remaining_rpm} / {MAX_RPM}")
        print(f"🔹 Sisa Request (Hari Ini)   : {remaining_rpd} / {MAX_RPD}")
        print(f"🔹 Sisa Token (Menit Ini)    : {remaining_tpm} / {MAX_TPM}")
        print("="*50 + "\n")

usage_tracker = RateTracker()

# ─────────────────────────────────────────────────────────────────────────────
# Gemini API Integration
# ─────────────────────────────────────────────────────────────────────────────
def _call_gemini_vision(img_bytes: bytes) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    
    b64_img = base64.b64encode(img_bytes).decode('utf-8')
    
    prompt = f"""
You are a highly accurate OCR system for reading shipping container numbers.
The container prefix is ALWAYS "{FIXED_PREFIX}".
Please find the 7 digits following the prefix (6-digit serial number and 1 check digit).
The text might be printed horizontally or vertically.
Return ONLY a valid JSON object matching this schema, without any markdown formatting or extra text.
{{
  "detected_digits": "the 7 digits you found (e.g. 1234567), or empty string if not found",
  "confidence_score": a number between 0.0 and 1.0 representing your confidence
}}
"""
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64_img
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "response_mime_type": "application/json"
        }
    }
    
    _log("Sending image to Gemini Vision API...")
    try:
        response = requests.post(url, json=payload, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        
        text_content = data['candidates'][0]['content']['parts'][0]['text']
        _log(f"Gemini raw response: {text_content}")
        
        # Parse JSON
        result = json.loads(text_content)
        
        total_tokens = 0
        if 'usageMetadata' in data:
            total_tokens = data['usageMetadata'].get('totalTokenCount', 0)
        usage_tracker.add_usage(total_tokens)
        
        return result
    except Exception as e:
        _log(f"Gemini API Error: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# Image helpers
# ─────────────────────────────────────────────────────────────────────────────
def _decode_image(image_bytes: bytes):
    arr = np.frombuffer(image_bytes, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)

def _encode_jpeg(img_bgr: np.ndarray) -> bytes:
    success, buffer = cv2.imencode('.jpg', img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not success:
        raise ValueError("Failed to encode image to JPEG")
    return buffer.tobytes()

def _resize_if_needed(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) > MAX_IMAGE_DIM:
        scale = MAX_IMAGE_DIM / float(max(h, w))
        return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img

def _draw_annotation(img: np.ndarray, detected_digits: str) -> np.ndarray:
    annotated = img.copy()
    if detected_digits:
        text = f"{FIXED_PREFIX}{detected_digits}"
        color = (0, 255, 0)
    else:
        text = "Not Found"
        color = (0, 0, 255)
        
    # Draw a box at the top left
    h, w = img.shape[:2]
    cv2.rectangle(annotated, (10, 10), (w - 10, 60), (0, 0, 0), -1)
    cv2.putText(annotated, f"LLM Result: {text}", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3, cv2.LINE_AA)
    return annotated

# ─────────────────────────────────────────────────────────────────────────────
# UI Builders
# ─────────────────────────────────────────────────────────────────────────────
def _build_success_result(digits: str, conf: float) -> dict:
    cn = FIXED_PREFIX + digits
    is_valid, calc_check = validate_iso6346(digits)
    
    grade = 'Grade : A' if conf >= 0.75 else 'Grade : B'
    status = 'success' if len(digits) == 7 else 'partial'
    
    return {
        'Nomor Container :': cn if status == 'success' else 'N/A',
        'Serial Number :': digits[:6] if len(digits) >= 6 else 'N/A',
        'Check Number :': digits[6] if len(digits) == 7 else 'N/A',
        'Grade': grade,
        'boxes': [], # Empty for LLM
        'prefix': FIXED_PREFIX,
        'detected_digits': digits,
        'serial_number': digits[:6] if len(digits) >= 6 else '',
        'check_digit': digits[6] if len(digits) == 7 else '',
        'ocr_confidence': conf,
        'orientation': 'LLM',
        'iso_valid': is_valid,
        'calculated_check_digit': calc_check,
        'status': status
    }

def _build_not_found_result() -> dict:
    return {
        'Nomor Container :': 'Not Found',
        'Serial Number :': 'Not Found',
        'Check Number :': 'Not Found',
        'Grade': 'Grade : Unknown',
        'boxes': [],
        'prefix': FIXED_PREFIX,
        'detected_digits': '',
        'serial_number': '',
        'check_digit': '',
        'ocr_confidence': 0.0,
        'orientation': 'unknown',
        'iso_valid': False,
        'calculated_check_digit': '',
        'status': 'error'
    }

def _build_error_result(err_msg: str) -> dict:
    res = _build_not_found_result()
    res['error'] = err_msg
    return res

# ─────────────────────────────────────────────────────────────────────────────
# Main Pipeline
# ─────────────────────────────────────────────────────────────────────────────
def process_pipeline(image_bytes: bytes, x_tolerance=100) -> tuple[np.ndarray | None, dict]:
    """
    Main entry point for Gemini-based OCR pipeline.
    """
    _log('--- Starting Gemini LLM Pipeline ---')
    t_start = time.time()
    
    try:
        # Decode & Resize
        img = _decode_image(image_bytes)
        if img is None:
            return None, _build_error_result('Failed to decode image.')
        
        img = _resize_if_needed(img)
        _save_debug(img, '01_original')
        
        # We need to send JPEG bytes to the API
        jpg_bytes = _encode_jpeg(img)
        
        # Call Gemini
        result = _call_gemini_vision(jpg_bytes)
        
        if result and result.get('detected_digits'):
            digits = str(result['detected_digits'])
            # Clean non-digits just in case
            digits = ''.join(filter(str.isdigit, digits))
            conf = float(result.get('confidence_score', 0.9))
            
            annotated_img = _draw_annotation(img, digits)
            
            if len(digits) >= 5:
                res_dict = _build_success_result(digits, conf)
            else:
                res_dict = _build_not_found_result()
                
            _log(f'Pipeline completed in {time.time() - t_start:.2f}s (LLM detected: {digits})')
            return annotated_img, res_dict
        else:
            _log(f'Pipeline completed in {time.time() - t_start:.2f}s (LLM returned Not Found)')
            annotated_img = _draw_annotation(img, "")
            return annotated_img, _build_not_found_result()
            
    except Exception as exc:
        _log(f'LLM pipeline failed: {exc}')
        # Generate a blank image if we can't even get img
        blank = np.zeros((100, 100, 3), dtype=np.uint8)
        return blank, _build_error_result(f'Pipeline error: {exc}')

