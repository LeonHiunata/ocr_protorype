from flask import Blueprint, request, jsonify
import base64
import cv2
from core.ocr_engine import process_pipeline
from middleware.error_handler import APIError

ocr_bp = Blueprint('ocr', __name__)

# Make a flag to share GPS_AVAILABLE with other modules, though it's typically set globally
# For now we'll import it from app or attempt import here.
try:
    from core import gps_reader
    GPS_AVAILABLE = True
except ImportError:
    GPS_AVAILABLE = False

# We use this to cache the last OCR result, similar to how it was done in app.py
_last_ocr_data = {}

@ocr_bp.route("/process-camera", methods=["POST"])
def process_camera():
    """
    Menerima gambar dari kamera browser dalam format base64 JSON.
    Mengembalikan hasil OCR sebagai JSON (tanpa page reload).
    """
    global _last_ocr_data
    try:
        payload = request.get_json(force=True)
        if not payload or 'image' not in payload:
            raise APIError('Tidak ada data gambar yang diterima.', 400)

        # Parse tolerance (default 100px)
        try:
            tolerance = int(payload.get('tolerance', 100))
        except (ValueError, TypeError):
            tolerance = 100

        # Decode base64 image (strip data URI header jika ada)
        image_b64 = payload['image']
        if ',' in image_b64:
            image_b64 = image_b64.split(',', 1)[1]
        
        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception as e:
            raise APIError(f'Gagal mendecode gambar base64: {str(e)}', 400)

        # Jalankan OCR pipeline
        annotated_img, extracted_data = process_pipeline(image_bytes, x_tolerance=tolerance)

        if annotated_img is None:
            raise APIError('Gagal memproses gambar. Pastikan gambar jelas dan berisi teks container.', 422)

        # Simpan hasil OCR untuk dipakai oleh send-to-database
        _last_ocr_data = extracted_data

        # Konversi hasil anotasi ke base64 JPEG untuk dikirim balik ke browser
        annotated_bgr = cv2.cvtColor(annotated_img, cv2.COLOR_RGB2BGR)
        _, buffer = cv2.imencode('.jpg', annotated_bgr)
        encoded_image = base64.b64encode(buffer).decode('utf-8')
        image_data_uri = f"data:image/jpeg;base64,{encoded_image}"

        # Hapus 'boxes' sebelum dikirim ke JSON (tidak serialisable)
        result_clean = {k: v for k, v in extracted_data.items() if k != 'boxes'}

        return jsonify({
            'success': True,
            'image_uri': image_data_uri,
            'results': result_clean,
            'gps_available': GPS_AVAILABLE
        })

    except APIError:
        raise
    except Exception as e:
        raise APIError(f'Terjadi kesalahan saat memproses OCR: {str(e)}', 500)
