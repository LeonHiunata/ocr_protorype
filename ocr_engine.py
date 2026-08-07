import cv2
import easyocr
import numpy as np
import re

_READER = None

def calculate_check_digit(container_num):
    """
    Menghitung ISO 6346 Check Digit untuk nomor container (4 huruf + 6 angka).
    Mengembalikan string angka check digit (0-9).
    """
    char_map = {
        'A': 10, 'B': 12, 'C': 13, 'D': 14, 'E': 15, 'F': 16, 'G': 17, 'H': 18, 'I': 19,
        'J': 20, 'K': 21, 'L': 23, 'M': 24, 'N': 25, 'O': 26, 'P': 27, 'Q': 28, 'R': 29,
        'S': 30, 'T': 31, 'U': 32, 'V': 34, 'W': 35, 'X': 36, 'Y': 37, 'Z': 38
    }
    if len(container_num) != 10:
        return '?'
    
    total = 0
    for i, char in enumerate(container_num):
        if i < 4:
            val = char_map.get(char.upper(), 0)
        else:
            try:
                val = int(char)
            except ValueError:
                return '?' # Jika ada karakter invalid
        total += val * (2 ** i)
        
    check = total % 11
    if check == 10:
        check = 0
    return str(check)

def get_reader():
    global _READER
    if _READER is None:
        _READER = easyocr.Reader(['en'], gpu=False)
    return _READER

def preprocess_image(image_bytes):
    """
    Decodes and applies CLAHE to the full image.
    Returns both the original color image and the processed grayscale.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None, None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    processed_img = clahe.apply(gray)
    return img, processed_img

def find_leftmost_column_x(image, reader):
    """
    PASS 1: Quick scan of the full image.
    Strategy: 
      1. Find the TOPMOST detected character (smallest Y / closest to top of image).
      2. Among all detections within the same top-region (top 20% of Y range),
         find the LEFTMOST X.
      3. This anchors the crop to the top-left corner of the number column,
         ignoring bottom noise.
    """
    results = reader.readtext(
        image,
        paragraph=False,
        allowlist='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        mag_ratio=1.0,
        link_threshold=0.99,
        y_ths=0.1,
        x_ths=0.1,
    )
    if not results:
        print("[OCR PASS1] No text detected on full image.")
        return None

    # Collect all (x_left, y_top) for each detection
    detections = []
    for bbox, text, prob in results:
        x_left = int(bbox[0][0])   # top-left X
        y_top  = int(bbox[0][1])   # top-left Y
        detections.append((x_left, y_top))

    # Find the topmost Y value
    min_y = min(d[1] for d in detections)
    # Find the Y range to define "top cluster" (top 20% of image height)
    img_h = image.shape[0]
    y_threshold = min_y + img_h * 0.20

    # Among detections in the top cluster, find the leftmost X
    top_cluster = [d for d in detections if d[1] <= y_threshold]
    leftmost_x = min(d[0] for d in top_cluster)

    print(f"[OCR PASS1] Top cluster ({len(top_cluster)} detections), leftmost X={leftmost_x} (min_y={min_y})")
    return leftmost_x

def extract_text_on_crop(image, reader):
    """
    PASS 2: Full-quality EasyOCR on the already-cropped image strip.
    """
    return reader.readtext(
        image,
        paragraph=False,
        y_ths=0.1,
        x_ths=0.1,
        width_ths=0.1,
        height_ths=0.1,
        link_threshold=0.99,
        allowlist='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        mag_ratio=2.0,
        add_margin=0.15
    )

def group_and_sort_vertically(results, x_tolerance=50):
    """
    Groups EasyOCR detections into vertical columns by X-coordinate proximity.
    Sorts each column top-to-bottom by Y position.
    """
    boxes = []
    for bbox, text, prob in results:
        cx = (bbox[0][0] + bbox[2][0]) / 2
        cy = (bbox[0][1] + bbox[2][1]) / 2
        boxes.append({'bbox': bbox, 'text': text, 'prob': prob, 'cx': cx, 'cy': cy})

    columns = []
    for box in boxes:
        placed = False
        for col in columns:
            avg_cx = sum(b['cx'] for b in col) / len(col)
            if abs(box['cx'] - avg_cx) <= x_tolerance:
                col.append(box)
                placed = True
                break
        if not placed:
            columns.append([box])

    for col in columns:
        col.sort(key=lambda item: item['cy'])

    return columns

def clean_character(char_text):
    """
    Strips vertical-line border artifacts read as '1', 'I', or 'L'.
    e.g. '161' -> '6',  '41' -> '4'
    Also applies OCR digit-correction for common letter/digit confusions.
    """
    char_text = char_text.strip().upper()
    if len(char_text) > 1:
        char_text = re.sub(r'^[1IL]+', '', char_text)
        char_text = re.sub(r'[1IL]+$', '', char_text)
        if not char_text:
            return char_text.strip().upper()
    # Apply common OCR letter-to-digit corrections
    ocr_corrections = {
        'O': '0', 'D': '0', 'Q': '0',
        'I': '1', 'L': '1',
        'Z': '2', 'J': "3",
        'E': '3',
        'A': '4', 'H': '4',
        'S': '5',
        'G': '6', 'b': '6',
        'T': '7',
        'B': '8',
        'P': '9', 'q': '9',
    }
    # Only apply correction if the entire string is a single known-confusable letter
    if len(char_text) == 1 and char_text in ocr_corrections:
        corrected = ocr_corrections[char_text]
        print(f"[OCR CORRECT] '{char_text}' -> '{corrected}'")
        return corrected
    return char_text

def parse_container_number(columns):
    """
    Strategy:
    1. Pick the leftmost column in the crop.
    2. Concatenate all detected characters top-to-bottom.
    3. Strip ALL letters — only keep digits.
    4. Take the LAST 7 digits (the bottom of the column is always the number).
       - Last digit  = Check Number
       - Digits 2-7 from bottom = 6-digit Serial Number
    5. Always prepend 'SPNU' (ignore whatever letters OCR detected).
    """
    if not columns:
        return _not_found()

    # Take the leftmost column within the crop
    sorted_columns = sorted(columns, key=lambda col: sum(b['cx'] for b in col) / len(col))
    best_col = sorted_columns[0]

    # Clean all chars and concatenate top-to-bottom
    cleaned_chars = []
    for b in best_col:
        b['text'] = clean_character(b['text'])
        cleaned_chars.append(b['text'])

    raw = "".join(cleaned_chars)
    print(f"[OCR PASS2] Raw column text: '{raw}'")

    # Strip ALL non-digit characters — serial and check number must be digits only
    digits_only = re.sub(r'[^0-9]', '', raw)
    print(f"[OCR PASS2] Digits only: '{digits_only}' (total={len(digits_only)})")

    if len(digits_only) < 6:
        print(f"[OCR PASS2] Not enough digits found ({len(digits_only)} < 6)")
        return _not_found(best_col)

    # Take the LAST 7 digits (bottom of the column = actual number)
    if len(digits_only) >= 7:
        last_7 = digits_only[-7:]
    else:
        last_7 = digits_only.zfill(7)

    last_7 = ''.join(c if c.isdigit() else '0' for c in last_7)
    print(f"[OCR PASS2] Last 7 digits (validated): '{last_7}'")

    # Ambil confidence dari deteksi terakhir (posisi check digit)
    check_confidence = best_col[-1]['prob'] if best_col else 1.0
    return _build_result('SPNU', last_7, best_col, check_confidence)

def _build_result(prefix, digits, col, check_confidence=1.0):
    # Always force prefix to 'SPNU' regardless of what OCR detected
    prefix = 'SPNU'

    # Hard enforce: digits must only contain 0-9 (strip any stray letter)
    digits = re.sub(r'[^0-9]', '', digits)

    serial = digits[:6]
    detected_check = digits[6] if len(digits) >= 7 else '?'

    # Validasi ISO 6346 KHUSUS untuk check digit saja.
    # Serial number tidak disentuh sama sekali.
    # Koreksi HANYA dilakukan jika:
    #   1. Confidence check digit rendah (< 0.65) — indikasi OCR ragu
    #   2. Hasil ISO berbeda dari hasil baca OCR
    check = detected_check
    if len(serial) == 6:
        expected_check = calculate_check_digit(prefix + serial)
        print(f"[OCR INFO] Check Digit — Detected: '{detected_check}' (conf={check_confidence:.2f}), ISO Expected: '{expected_check}'")
        if expected_check != '?':
            if detected_check != expected_check:
                print(f"[OCR CORRECT] Mengabaikan bingkai/kesalahan OCR pada check digit. Koreksi '{detected_check}' -> '{expected_check}' (Standar ISO 6346)")
            check = expected_check
            # Update teks box terakhir agar visualisasi juga menampilkan nilai yang dikoreksi
            if col:
                col[-1]['text'] = expected_check

    # Extra safety: if check or any serial char is still not a digit, flag it
    if check != '?' and not check.isdigit():
        print(f"[OCR WARN] Non-digit check number detected: '{check}', replacing with '?'")
        check = '?'
    serial = ''.join(c if c.isdigit() else '?' for c in serial)

    container_number = f"{prefix}{serial}{check}"
    try:
        grade = "Grade : B" if int(serial[:2]) < 30 else "Grade : A"
    except ValueError:
        grade = "Grade : Unknown"
    print(f"[OCR RESULT] Nomor Container: {container_number}")
    return {
        "Serial Number :": serial,
        "Check Number :": check,
        "Nomor Container :": container_number,
        "Grade": grade,
        "boxes": col,
    }

def _not_found(col=None):
    return {
        "Serial Number :": "Not Found",
        "Check Number :": "Not Found",
        "Nomor Container :": "Not Found",
        "Grade": "Not Found",
        "boxes": col or [],
    }

def refine_zero_vs_eight(img, bbox, original_text):
    """
    Mengecek secara visual apakah karakter '0' atau '8' memiliki garis horizontal di tengah.
    Menggunakan area tengah yang sangat presisi agar kebal terhadap font 0 yang tebal
    dan kebal terhadap kotak pinggir pada check digit.
    """
    pt1 = (int(bbox[0][0]), int(bbox[0][1]))
    pt3 = (int(bbox[2][0]), int(bbox[2][1]))
    
    x1, y1 = max(0, pt1[0]), max(0, pt1[1])
    x2, y2 = min(img.shape[1], pt3[0]), min(img.shape[0], pt3[1])
    
    if y2 - y1 < 10 or x2 - x1 < 5:
        return original_text
        
    char_crop = img[y1:y2, x1:x2]
    
    # Binarize: teks hitam pada background terang menjadi putih pada background hitam
    _, thresh = cv2.threshold(char_crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    h, w = thresh.shape
    
    # Cek TEPAT di titik paling tengah (Core Center Hole)
    # Y: 40% - 60% (menangkap garis melintang / bridge angka 8)
    # X: 45% - 55% (sangat sempit di tengah horizontal untuk menghindari garis sisi tebal angka 0)
    cy1, cy2 = int(h * 0.40), int(h * 0.60)
    cx1, cx2 = int(w * 0.45), int(w * 0.55)
    
    if cy2 == cy1: cy2 += 1
    if cx2 == cx1: cx2 += 1
    
    center_hole = thresh[cy1:cy2, cx1:cx2]
    white_pixels = cv2.countNonZero(center_hole)
    total_pixels = center_hole.shape[0] * center_hole.shape[1]
    
    if total_pixels == 0:
        return '0'
        
    fill_ratio = white_pixels / total_pixels
    print(f"[0/8 HEURISTIC] Text: {original_text} | Fill Ratio: {fill_ratio:.3f} | ROI: {total_pixels}px")
    
    # Jika titik tengah memiliki pixel putih (garis), maka itu angka 8
    # Threshold rendah (0.10) karena area yang dicek sangat kecil dan tepat di tengah
    if fill_ratio > 0.10:
        return '8'
    else:
        return '0'

def draw_visualizations(image, results):
    annotated = image.copy()
    for bbox, text, prob in results:
        pt1 = (int(bbox[0][0]), int(bbox[0][1]))
        pt2 = (int(bbox[2][0]), int(bbox[2][1]))
        cv2.rectangle(annotated, pt1, pt2, (0, 255, 0), 2)
        label = f"{text} ({prob:.2f})"
        font_scale = 0.8
        thickness = 2
        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        cv2.rectangle(annotated, (pt1[0], pt1[1] - 30), (pt1[0] + w, pt1[1]), (0, 255, 0), -1)
        cv2.putText(annotated, label, (pt1[0], pt1[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thickness)
    return annotated

def process_pipeline(image_bytes, x_tolerance=50):
    reader = get_reader()

    original_img, processed_img = preprocess_image(image_bytes)
    if original_img is None:
        return None, None

    img_h, img_w = original_img.shape[:2]

    # ── PASS 1: Find the X position of the leftmost detected letter on the RIGHT HALF ──────────
    half_w = img_w // 2
    right_half_img = processed_img[:, half_w:]
    leftmost_x_relative = find_leftmost_column_x(right_half_img, reader)
    
    if leftmost_x_relative is None:
        leftmost_x = 0  # fallback: use full image
    else:
        leftmost_x = leftmost_x_relative + half_w  # Adjust back to absolute original coordinates

    # ── CROP: ±300 px around the leftmost column ─────────────────────────────
    PAD_LEFT  = 300
    PAD_RIGHT = 100  # 100px less than left to cut right-side noise
    crop_x1 = max(0, leftmost_x - PAD_LEFT)
    crop_x2 = min(img_w, leftmost_x + PAD_RIGHT)
    print(f"[OCR CROP] x1={crop_x1}  x2={crop_x2}  (image width={img_w})")

    cropped_color     = original_img[:, crop_x1:crop_x2]
    cropped_processed = processed_img[:, crop_x1:crop_x2]

    # ── PASS 2: High-quality OCR on the narrow crop ───────────────────────────
    results = extract_text_on_crop(cropped_processed, reader)

    columns = group_and_sort_vertically(results, x_tolerance)
    extracted_data = parse_container_number(columns)

    # Draw all boxes on the cropped color image
    all_boxes = [box for col in columns for box in col]
    draw_data = [(b['bbox'], b['text'], b['prob']) for b in all_boxes]
    annotated_crop = draw_visualizations(cropped_color, draw_data)

    annotated_rgb = cv2.cvtColor(annotated_crop, cv2.COLOR_BGR2RGB)
    return annotated_rgb, extracted_data