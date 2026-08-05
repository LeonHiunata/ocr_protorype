import os
import cv2
import easyocr
import numpy as np
import re
import torch

_READER = None

if not torch.cuda.is_available():
    torch.set_num_threads(min(4, os.cpu_count() or 4))

def calculate_check_digit(container_num):
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
                return '?'
        total += val * (2 ** i)
    check = total % 11
    if check == 10:
        check = 0
    return str(check)

def get_reader():
    global _READER
    if _READER is None:
        _READER = easyocr.Reader(['en'], gpu=torch.cuda.is_available())
    return _READER

def preprocess_image(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None, None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return img, clahe.apply(gray)

def clean_character(char_text):
    if not char_text:
        return '?'
    char_text = char_text.strip().upper()
    if len(char_text) > 1:
        char_text = re.sub(r'^[1IL|]+', '', char_text)
        char_text = re.sub(r'[1IL|]+$', '', char_text)
        if not char_text:
            return '1'
    corrections = {
        'O': '0', 'D': '0', 'Q': '0',
        'I': '1', 'L': '1', 'T': '1', '|': '1',
        'Z': '2', 'E': '3', 'A': '4', 'H': '4',
        'S': '5', 'G': '6', 'B': '8', 'P': '9',
    }
    if len(char_text) == 1 and char_text in corrections:
        return corrections[char_text]
    return char_text

def refine_zero_vs_eight(img, bbox, text):
    if text not in ['0', '8']:
        return text
    x1, y1 = max(0, int(bbox[0][0])), max(0, int(bbox[0][1]))
    x2, y2 = min(img.shape[1], int(bbox[2][0])), min(img.shape[0], int(bbox[2][1]))
    if y2 - y1 < 10 or x2 - x1 < 5:
        return text
    crop = img[y1:y2, x1:x2]
    if crop.ndim == 3:
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(thresh) > 140:
        thresh = cv2.bitwise_not(thresh)
    h, w = thresh.shape
    cy1, cy2 = max(0, int(h*0.40)), min(h, int(h*0.60))
    cx1, cx2 = max(0, int(w*0.30)), min(w, int(w*0.70))
    if cy2 <= cy1 or cx2 <= cx1:
        return text
    center = thresh[cy1:cy2, cx1:cx2]
    total = center.shape[0] * center.shape[1]
    if total == 0:
        return text
    return '8' if (cv2.countNonZero(center) / total) > 0.20 else '0'

def _tighten_contour(image, x1, y1, x2, y2, roi):
    """Perketat bounding box sesuai kontur fisik digit tunggal."""
    box_h, box_w = y2 - y1, x2 - x1
    orig = [[float(x1), float(y1)], [float(x2), float(y1)],
            [float(x2), float(y2)], [float(x1), float(y2)]]
    if box_h < 10 or box_w < 5 or roi.size == 0:
        return orig, False
    img_h, img_w = image.shape[:2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi.copy()
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(thresh) > 140:
        thresh = cv2.bitwise_not(thresh)
    cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = []
    for c in cnts:
        cx, cy, cw, ch = cv2.boundingRect(c)
        if cw * ch >= 20 and ch >= 8 and cw >= 3:
            valid.append((c, cx, cy, cw, ch, cw*ch))
    if not valid:
        return orig, False
    max_area = max(v[5] for v in valid)
    main = [v[0] for v in valid if v[5] >= 0.15 * max_area]
    pts = np.vstack(main)
    mcx, mcy, mcw, mch = cv2.boundingRect(pts)
    if mch < int(0.50 * box_h) or mcw < int(0.30 * box_w):
        return orig, False
    pad = 2
    tx1 = max(0, x1 + mcx - pad)
    ty1 = max(0, y1 + mcy - pad)
    tx2 = min(img_w, x1 + mcx + mcw + pad)
    ty2 = min(img_h, y1 + mcy + mch + pad)
    return [[float(tx1), float(ty1)], [float(tx2), float(ty1)],
            [float(tx2), float(ty2)], [float(tx1), float(ty2)]], True

def split_merged_box(image, bbox, text, prob, reader):
    """
    Pecah box yang berisi banyak digit vertikal menjadi box TEPAT 1 DIGIT per box.
    Gunakan kontur fisik untuk mendapatkan batas per-digit yang tepat.
    """
    img_h, img_w = image.shape[:2]
    x1 = max(0, int(bbox[0][0]))
    y1 = max(0, int(bbox[0][1]))
    x2 = min(img_w, int(bbox[2][0]))
    y2 = min(img_h, int(bbox[2][1]))
    box_h = y2 - y1
    box_w = max(1, x2 - x1)

    if box_h < 8 or box_w < 4:
        return []

    aspect_ratio = box_h / float(box_w)
    digits_only = "".join(c for c in text if c.isdigit())
    num_digits = len(digits_only)

    # Estimasi jumlah digit berdasarkan aspect ratio dan teks
    est_n = max(num_digits, int(round(aspect_ratio / 1.35)))

    # Sudah single digit
    if est_n <= 1 and aspect_ratio < 2.0:
        roi = image[y1:y2, x1:x2]
        tight_b, _ = _tighten_contour(image, x1, y1, x2, y2, roi)
        char = digits_only[0] if digits_only else clean_character(text[:1])
        char = refine_zero_vs_eight(image, tight_b, char)
        return [(tight_b, char, prob)]

    # TALL BOX — wajib dipecah menjadi est_n single-digit box
    print(f"[SPLIT] Memecah box jangkung H={box_h}px AR={aspect_ratio:.2f} -> {est_n} digit")
    roi = image[y1:y2, x1:x2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi.copy()
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(thresh) > 140:
        thresh = cv2.bitwise_not(thresh)

    # Gunakan horizontal projection profile untuk menemukan batas antar-digit
    h_proj = np.sum(thresh, axis=1).astype(float)
    h_proj_norm = h_proj / max(1.0, h_proj.max())

    # Temukan lembah (valleys) dalam proyeksi horizontal sebagai pemisah digit
    # Lembah = area dengan sedikit piksel putih (< 10% dari maks)
    in_digit = False
    digit_spans = []
    start = 0
    for r in range(len(h_proj_norm)):
        is_digit_row = h_proj_norm[r] > 0.08
        if is_digit_row and not in_digit:
            start = r
            in_digit = True
        elif not is_digit_row and in_digit:
            if r - start >= 6:  # minimal 6px tinggi per digit
                digit_spans.append((start, r))
            in_digit = False
    if in_digit and len(h_proj_norm) - start >= 6:
        digit_spans.append((start, len(h_proj_norm)))

    print(f"[SPLIT] Ditemukan {len(digit_spans)} span dari proyeksi horizontal")

    results = []
    if len(digit_spans) >= 2:
        # Gunakan span dari proyeksi horizontal
        for (dy1, dy2) in digit_spans:
            pad = 2
            sy1 = max(0, y1 + dy1 - pad)
            sy2 = min(img_h, y1 + dy2 + pad)
            crop = image[sy1:sy2, x1:x2]
            if crop.size == 0:
                continue
            sub_ocr = reader.readtext(
                crop, allowlist='0123456789', paragraph=False,
                mag_ratio=1.3, add_margin=0.0
            )
            if sub_ocr:
                sub_text = clean_character(sub_ocr[0][1])
                sub_prob  = sub_ocr[0][2]
            else:
                sub_text = '?'
                sub_prob  = prob * 0.80
            sub_b = [[float(x1), float(sy1)], [float(x2), float(sy1)],
                     [float(x2), float(sy2)], [float(x1), float(sy2)]]
            tight_b, ok = _tighten_contour(image, x1, sy1, x2, sy2, crop)
            final_b = tight_b if ok else sub_b
            char = (sub_text[0] if sub_text else '?')
            char = refine_zero_vs_eight(image, final_b, char)
            if char != '?':
                results.append((final_b, char, max(sub_prob, 0.20)))
    else:
        # Fallback: potong rata sejumlah est_n
        sub_h = box_h / float(est_n)
        for i in range(est_n):
            sy1 = int(y1 + i * sub_h)
            sy2 = int(y1 + (i + 1) * sub_h)
            crop = image[sy1:sy2, x1:x2]
            if crop.size == 0:
                continue
            sub_ocr = reader.readtext(
                crop, allowlist='0123456789', paragraph=False,
                mag_ratio=1.3, add_margin=0.0
            )
            tight_b, ok = _tighten_contour(image, x1, sy1, x2, sy2, crop)
            if sub_ocr:
                sub_text = clean_character(sub_ocr[0][1])
                sub_prob  = sub_ocr[0][2]
            else:
                sub_text = digits_only[i] if i < len(digits_only) else '?'
                sub_prob  = prob * 0.75
            char = (sub_text[0] if sub_text else '?')
            char = refine_zero_vs_eight(image, tight_b, char)
            if char != '?':
                results.append((tight_b, char, max(sub_prob, 0.20)))

    return results

def detect_single_digits(image, reader, min_conf=0.20):
    """
    Deteksi semua angka di gambar dengan link_threshold=0.99 agar
    setiap box tetap terpisah per-digit (tidak digabung horizontal).
    Setiap box yang masih menggabungkan banyak digit DIPAKSA dipecah.
    """
    # link_threshold=0.99 mencegah EasyOCR menggabungkan digit-digit berdekatan
    raw = reader.readtext(
        image,
        paragraph=False,
        y_ths=0.01,
        x_ths=0.01,
        width_ths=0.01,
        height_ths=0.01,
        link_threshold=0.99,
        allowlist='0123456789',
        mag_ratio=1.0,
        batch_size=4,
        add_margin=0.0
    )

    all_single = []
    for bbox, text, prob in raw:
        if prob < min_conf:
            continue
        boxes = split_merged_box(image, bbox, text, prob, reader)
        all_single.extend(boxes)

    return all_single

def compute_overlap(box1, box2):
    x1a, y1a = float(box1[0][0]), float(box1[0][1])
    x2a, y2a = float(box1[2][0]), float(box1[2][1])
    x1b, y1b = float(box2[0][0]), float(box2[0][1])
    x2b, y2b = float(box2[2][0]), float(box2[2][1])
    iw = max(0.0, min(x2a, x2b) - max(x1a, x1b))
    ih = max(0.0, min(y2a, y2b) - max(y1a, y1b))
    ia = iw * ih
    min_area = min(max(1.0, (x2a-x1a)*(y2a-y1a)), max(1.0, (x2b-x1b)*(y2b-y1b)))
    min_h = min(abs(y2a-y1a), abs(y2b-y1b))
    v_ov = ih / min_h if min_h > 0 else 0.0
    return max(ia / min_area, v_ov)

def nms(boxes, overlap_thresh=0.30, min_conf=0.20):
    valid = [b for b in boxes if b[2] >= min_conf]
    valid.sort(key=lambda b: b[2], reverse=True)
    kept = []
    for item in valid:
        bbox, text, prob = item
        if not any(compute_overlap(bbox, k[0]) > overlap_thresh for k in kept):
            kept.append(item)
    kept.sort(key=lambda b: (b[0][0][1] + b[0][2][1]) / 2.0)
    return kept

def pick_container_column(all_boxes, x_tolerance=35):
    """
    Pilih kolom vertikal yang merupakan kolom nomor container.
    Kriteria:
    - Paling banyak digit
    - Pitch (jarak antar-digit vertikal) yang konsisten dan seragam
    - Ukuran digit yang seragam (bukan elemen kecil seperti IC 70)
    """
    if not all_boxes:
        return []

    items = []
    for bbox, text, prob in all_boxes:
        cx = (bbox[0][0] + bbox[2][0]) / 2.0
        cy = (bbox[0][1] + bbox[2][1]) / 2.0
        w  = max(1.0, float(bbox[2][0] - bbox[0][0]))
        h  = max(1.0, float(bbox[2][1] - bbox[0][1]))
        items.append({'bbox': bbox, 'text': text, 'prob': prob,
                      'cx': cx, 'cy': cy, 'w': w, 'h': h})

    # Kelompokkan ke dalam kolom
    columns = []
    for item in items:
        placed = False
        for col in columns:
            avg_cx = sum(b['cx'] for b in col) / len(col)
            if abs(item['cx'] - avg_cx) <= x_tolerance:
                col.append(item)
                placed = True
                break
        if not placed:
            columns.append([item])

    for col in columns:
        col.sort(key=lambda b: b['cy'])

    def column_score(col):
        n = len(col)
        if n < 2:
            return 0.0
        # Bobot utama: jumlah digit (container punya 7-10 digit)
        score = float(n) * 3.0
        # Konsistensi pitch
        cys = [b['cy'] for b in col]
        diffs = [cys[i+1] - cys[i] for i in range(len(cys)-1)]
        if len(diffs) > 1:
            pitch_cv = np.std(diffs) / max(1.0, np.mean(diffs))
            score += max(0.0, 1.0 - pitch_cv) * 5.0  # bonus konsistensi
        # Ukuran digit (harus cukup besar, bukan label kecil)
        avg_h = np.mean([b['h'] for b in col])
        avg_w = np.mean([b['w'] for b in col])
        if avg_h >= 20 and avg_w >= 10:
            score += 3.0
        elif avg_h < 10:
            score -= 5.0  # penalti untuk elemen sangat kecil
        # Bonus confidence rata-rata
        score += np.mean([b['prob'] for b in col]) * 2.0
        return score

    best = max(columns, key=column_score)
    print(f"[COLUMN] Best: {len(best)} digits, score={column_score(best):.2f}, "
          f"cx={sum(b['cx'] for b in best)/len(best):.1f}")
    return best

def parse_container_number(col):
    if not col:
        return _not_found()

    cleaned = []
    for b in col:
        c = clean_character(b['text'])
        b['text'] = c
        if c and c.isdigit():
            cleaned.append(b)

    raw_digits = "".join(b['text'] for b in cleaned)
    print(f"[OCR] Column digits: '{raw_digits}' ({len(raw_digits)})")

    if len(raw_digits) < 6:
        return _not_found(col)

    target_digits = raw_digits[-7:] if len(raw_digits) >= 7 else raw_digits.zfill(7)
    target_items  = cleaned[-7:] if len(cleaned) >= 7 else cleaned

    prefix = "SPNU"
    serial    = target_digits[:6]
    det_check = target_digits[6] if len(target_digits) >= 7 else '?'
    final_serial, final_check = serial, det_check
    exp_check = calculate_check_digit(prefix + serial)
    print(f"[ISO] detected='{det_check}', expected='{exp_check}'")

    if exp_check != '?' and det_check != exp_check:
        fixed = False
        for pos in range(6):
            orig = serial[pos]
            for c in range(10):
                test = serial[:pos] + str(c) + serial[pos+1:]
                if calculate_check_digit(prefix + test) == det_check:
                    print(f"[ISO FIX] pos={pos}: '{orig}'->'{c}'")
                    final_serial = test
                    fixed = True
                    if pos < len(target_items):
                        target_items[pos]['text'] = str(c)
                    break
            if fixed:
                break
        if not fixed:
            final_check = exp_check
            if target_items:
                target_items[-1]['text'] = exp_check

    container = f"{prefix}{final_serial}{final_check}"
    try:
        grade = "Grade : B" if int(final_serial[:2]) < 30 else "Grade : A"
    except ValueError:
        grade = "Grade : Unknown"
    print(f"[RESULT] {container}")
    return {
        "Serial Number :":   final_serial,
        "Check Number :":    final_check,
        "Nomor Container :": container,
        "Grade":             grade,
        "boxes":             target_items,
    }

def _not_found(col=None):
    return {"Serial Number :": "Not Found", "Check Number :": "Not Found",
            "Nomor Container :": "Not Found", "Grade": "Not Found", "boxes": col or []}

def draw_visualizations(image, col):
    """
    Gambar bounding box HANYA untuk digit-digit dalam kolom container terpilih.
    Setiap box adalah persegi kecil yang membungkus tepat 1 digit.
    """
    annotated = image.copy()
    for b in col:
        bbox = b['bbox']
        text = b.get('text', '')
        prob = b.get('prob', 0.0)
        if not text or not any(c.isdigit() for c in text):
            continue
        pt1 = (int(bbox[0][0]), int(bbox[0][1]))
        pt2 = (int(bbox[2][0]), int(bbox[2][1]))
        cv2.rectangle(annotated, pt1, pt2, (0, 255, 0), 2)
        label = f"{text} ({prob:.2f})"
        fs, th = 0.50, 1
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
        cv2.rectangle(annotated, (pt1[0], pt1[1]-16), (pt1[0]+lw, pt1[1]), (0, 255, 0), -1)
        cv2.putText(annotated, label, (pt1[0], pt1[1]-3),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), th)
    return annotated

def process_pipeline(image_bytes, x_tolerance=35, min_confidence=0.20):
    reader = get_reader()
    original_img, processed_img = preprocess_image(image_bytes)
    if original_img is None:
        return None, None

    img_h, img_w = original_img.shape[:2]

    # Deteksi semua angka pada SELURUH gambar dengan link_threshold=0.99
    print("[OCR] Detecting per-digit boxes on full image...")
    all_single = detect_single_digits(processed_img, reader, min_conf=min_confidence)
    all_single  = nms(all_single, overlap_thresh=0.30, min_conf=min_confidence)
    print(f"[OCR] Total per-digit boxes: {len(all_single)}")

    # Pilih kolom container terbaik berdasarkan score
    best_col = pick_container_column(all_single, x_tolerance=x_tolerance)

    extracted_data = parse_container_number(best_col)

    # Tentukan area crop berdasarkan kolom terpilih + margin
    if best_col:
        all_xs = [b['bbox'][0][0] for b in best_col] + [b['bbox'][2][0] for b in best_col]
        col_x1 = max(0, int(min(all_xs)) - 80)
        col_x2 = min(img_w, int(max(all_xs)) + 80)
    else:
        col_x1, col_x2 = 0, img_w

    cropped_color = original_img[:, col_x1:col_x2]

    # Offset koordinat bbox ke ruang koordinat crop
    offset_col = []
    for b in best_col:
        nb = [[pt[0] - col_x1, pt[1]] for pt in b['bbox']]
        offset_col.append({**b, 'bbox': nb})

    annotated_crop = draw_visualizations(cropped_color, offset_col)
    annotated_rgb  = cv2.cvtColor(annotated_crop, cv2.COLOR_BGR2RGB)
    return annotated_rgb, extracted_data
