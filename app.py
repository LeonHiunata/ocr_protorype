import base64
import sys
import os
import math
import cv2
import json
import time
import numpy as np
from flask import Flask, request, render_template, jsonify, Response
from datetime import datetime, timedelta, timezone

# Import OCR pipeline
from ocr_engine import process_pipeline

# Import GPS modules (copied from apk_deteksi_container)
try:
    import gps_reader
    import parsing as gps_parsing
    GPS_AVAILABLE = True
except ImportError:
    GPS_AVAILABLE = False
    print("[WARN] gps_reader / parsing modules not found. GPS features disabled.")

try:
    import counter
    COUNTER_AVAILABLE = True
except ImportError:
    COUNTER_AVAILABLE = False
    print("[WARN] counter module not found.")

app = Flask(__name__)

# ─────────────────────────────────────────────
# UTM Conversion Helper (WGS84, no external lib)
# ─────────────────────────────────────────────

def latlon_to_utm(lat, lon):
    """
    Konversi decimal lat/lon (WGS84) ke koordinat UTM.
    Mengembalikan (easting, northing, zone_number, zone_letter).
    """
    a  = 6378137.0           # semi-major axis WGS84
    f  = 1 / 298.257223563   # flattening
    k0 = 0.9996              # scale factor

    e2        = 2*f - f**2
    e_prime2  = e2 / (1 - e2)

    zone_number = int((lon + 180) / 6) + 1
    lon_origin  = (zone_number - 1) * 6 - 180 + 3  # central meridian

    lat_r  = math.radians(lat)
    lon_r  = math.radians(lon)
    lon0_r = math.radians(lon_origin)

    N = a / math.sqrt(1 - e2 * math.sin(lat_r)**2)
    T = math.tan(lat_r)**2
    C = e_prime2 * math.cos(lat_r)**2
    A = math.cos(lat_r) * (lon_r - lon0_r)

    # Meridional arc
    e4 = e2**2; e6 = e2**3
    M = a * (
        (1 - e2/4 - 3*e4/64 - 5*e6/256) * lat_r
        - (3*e2/8 + 3*e4/32 + 45*e6/1024) * math.sin(2*lat_r)
        + (15*e4/256 + 45*e6/1024) * math.sin(4*lat_r)
        - (35*e6/3072) * math.sin(6*lat_r)
    )

    easting = k0 * N * (
        A
        + (1 - T + C) * A**3 / 6
        + (5 - 18*T + T**2 + 72*C - 58*e_prime2) * A**5 / 120
    ) + 500000.0

    northing = k0 * (
        M + N * math.tan(lat_r) * (
            A**2 / 2
            + (5 - T + 9*C + 4*C**2) * A**4 / 24
            + (61 - 58*T + T**2 + 600*C - 330*e_prime2) * A**6 / 720
        )
    )

    if lat < 0:
        northing += 10000000.0  # southern hemisphere offset

    # Zone letter (simplified MGRS band)
    zone_letters = 'CDEFGHJKLMNPQRSTUVWXX'
    zone_letter  = zone_letters[int((lat + 80) / 8)] if -80 <= lat <= 84 else '?'

    return round(easting, 2), round(northing, 2), zone_number, zone_letter

# ─────────────────────────────────────────────
# Session storage for last OCR result (in-memory, single-user)
# ─────────────────────────────────────────────
_last_ocr_data = {}


# ─────────────────────────────────────────────
# OCR Routes
# ─────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/process-camera", methods=["POST"])
def process_camera():
    """
    Menerima gambar dari kamera browser dalam format base64 JSON.
    Mengembalikan hasil OCR sebagai JSON (tanpa page reload).
    """
    global _last_ocr_data
    try:
        payload = request.get_json(force=True)
        if not payload or 'image' not in payload:
            return jsonify({'error': 'Tidak ada data gambar yang diterima.'}), 400

        # Parse tolerance (default 150px)
        try:
            tolerance = int(payload.get('tolerance', 100))
        except (ValueError, TypeError):
            tolerance = 100

        # Decode base64 image (strip data URI header jika ada)
        image_b64 = payload['image']
        if ',' in image_b64:
            image_b64 = image_b64.split(',', 1)[1]
        image_bytes = base64.b64decode(image_b64)

        # Jalankan OCR pipeline
        annotated_img, extracted_data = process_pipeline(image_bytes, x_tolerance=tolerance)

        if annotated_img is None:
            return jsonify({'error': 'Gagal memproses gambar. Pastikan gambar jelas dan berisi teks container.'}), 422

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

    except Exception as e:
        return jsonify({'error': f'Terjadi kesalahan: {str(e)}'}), 500


# ─────────────────────────────────────────────
# GPS Real-Time Routes
# ─────────────────────────────────────────────

@app.route('/current-status')
def current_status():
    """Lightweight polling endpoint untuk status GPS fix terkini (non-blocking)."""
    if not GPS_AVAILABLE:
        return jsonify({'error': 'GPS module tidak tersedia.'}), 503
    try:
        status = gps_reader.get_current_fix()
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/live-location')
def live_location():
    """Endpoint real-time telemetri posisi rover terkini (lat/lon, UTM, slot, trail)."""
    if not GPS_AVAILABLE:
        return jsonify({'error': 'GPS module tidak tersedia.'}), 503
    try:
        fix = gps_reader.get_current_fix()
        lat = fix.get('latitude')
        lon = fix.get('longitude')

        utm_e, utm_n, utm_zone_str = None, None, None
        detected_slot, rot_x, rot_y = None, None, None

        if lat is not None and lon is not None:
            utm_e, utm_n, utm_z, utm_l = latlon_to_utm(float(lat), float(lon))
            utm_zone_str = f"{utm_z}{utm_l}"

            if COUNTER_AVAILABLE:
                try:
                    hasil_counter, rot_x, rot_y = counter.deteksi_blok(float(lon), float(lat))
                    if hasil_counter:
                        detected_slot = hasil_counter[2]
                except Exception:
                    pass

        time_wib = datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=7))
        ).strftime('%Y-%m-%d %H:%M:%S WIB')

        trail = gps_reader.get_trail()

        return jsonify({
            'latitude': lat,
            'longitude': lon,
            'altitude': fix.get('altitude', 0.0),
            'gps_quality': fix.get('gps_quality', 0),
            'rtk_status': fix.get('rtk_status', 'NO FIX'),
            'num_sats': fix.get('num_sats', 0),
            'connected': fix.get('connected', False),
            'simulation': fix.get('simulation', False),
            'utc_time': fix.get('utc_time'),
            'ts': fix.get('ts'),
            'time_wib': time_wib,
            'easting': utm_e,
            'northing': utm_n,
            'utm_zone': utm_zone_str,
            'rot_x': rot_x,
            'rot_y': rot_y,
            'detected_slot': detected_slot,
            'trail': trail
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/stream-gps')
def stream_gps():
    """Server-Sent Events (SSE) stream untuk update posisi rover secara langsung."""
    if not GPS_AVAILABLE:
        return jsonify({'error': 'GPS module tidak tersedia.'}), 503

    def generate_events():
        while True:
            try:
                fix = gps_reader.get_current_fix()
                lat = fix.get('latitude')
                lon = fix.get('longitude')

                utm_e, utm_n, utm_zone_str = None, None, None
                detected_slot, rot_x, rot_y = None, None, None

                if lat is not None and lon is not None:
                    utm_e, utm_n, utm_z, utm_l = latlon_to_utm(float(lat), float(lon))
                    utm_zone_str = f"{utm_z}{utm_l}"

                    if COUNTER_AVAILABLE:
                        try:
                            hasil_counter, rot_x, rot_y = counter.deteksi_blok(float(lon), float(lat))
                            if hasil_counter:
                                detected_slot = hasil_counter[2]
                        except Exception:
                            pass

                time_wib = datetime.now(timezone.utc).astimezone(
                    timezone(timedelta(hours=7))
                ).strftime('%Y-%m-%d %H:%M:%S WIB')

                data = {
                    'latitude': lat,
                    'longitude': lon,
                    'altitude': fix.get('altitude', 0.0),
                    'gps_quality': fix.get('gps_quality', 0),
                    'rtk_status': fix.get('rtk_status', 'NO FIX'),
                    'num_sats': fix.get('num_sats', 0),
                    'connected': fix.get('connected', False),
                    'simulation': fix.get('simulation', False),
                    'utc_time': fix.get('utc_time'),
                    'ts': fix.get('ts'),
                    'time_wib': time_wib,
                    'easting': utm_e,
                    'northing': utm_n,
                    'utm_zone': utm_zone_str,
                    'rot_x': rot_x,
                    'rot_y': rot_y,
                    'detected_slot': detected_slot,
                    'trail': gps_reader.get_trail()
                }

                yield f"data: {json.dumps(data)}\n\n"
                time.sleep(0.3)
            except Exception as ex:
                yield f"data: {json.dumps({'error': str(ex)})}\n\n"
                time.sleep(1.0)

    return Response(generate_events(), mimetype='text/event-stream')


@app.route('/toggle-simulation', methods=['POST', 'GET'])
def toggle_simulation():
    """Aktifkan / matikan mode simulasi gerak rover."""
    if not GPS_AVAILABLE:
        return jsonify({'error': 'GPS module tidak tersedia.'}), 503
    try:
        if request.method == 'POST':
            payload = request.get_json(silent=True) or {}
            enabled = payload.get('enabled', None)
            if enabled is None:
                enabled = not gps_reader.is_simulation_mode()
        else:
            state = request.args.get('enabled', '')
            if state.lower() in ('true', '1', 'yes'):
                enabled = True
            elif state.lower() in ('false', '0', 'no'):
                enabled = False
            else:
                enabled = not gps_reader.is_simulation_mode()

        res = gps_reader.set_simulation_mode(enabled)
        return jsonify({
            'success': True,
            'simulation_enabled': res,
            'message': f"Mode simulasi pergerakan rover {'diaktifkan' if res else 'dimatikan'}."
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/check-location')
def check_location():
    """
    Kumpulkan pembacaan GPS selama beberapa detik lalu kembalikan rata-rata.
    """
    if not GPS_AVAILABLE:
        return jsonify({'error': 'GPS module tidak tersedia.'}), 503
    try:
        # Jika simulasi aktif atau data langsung sudah ada, langsung berikan live location
        fix = gps_reader.get_current_fix()
        if fix.get('simulation') or fix.get('latitude') is not None:
            lat = fix.get('latitude')
            lon = fix.get('longitude')
            if lat is not None and lon is not None:
                utm_e, utm_n, utm_zone, utm_letter = latlon_to_utm(float(lat), float(lon))
                detected_slot = None
                rot_x, rot_y = None, None
                if COUNTER_AVAILABLE:
                    try:
                        hasil_counter, rot_x, rot_y = counter.deteksi_blok(float(lon), float(lat))
                        if hasil_counter:
                            detected_slot = hasil_counter[2]
                    except Exception:
                        pass

                time_wib = datetime.now(timezone.utc).astimezone(
                    timezone(timedelta(hours=7))
                ).strftime('%Y-%m-%d %H:%M:%S WIB')

                return jsonify({
                    'avg_lon': float(lon),
                    'avg_lat': float(lat),
                    'avg_alt': float(fix.get('altitude', 0.0)),
                    'count': 1,
                    'fix_count': 1,
                    'used_fix_data': True,
                    'avg_fix_quality': int(fix.get('gps_quality', 4)),
                    'avg_rtk_status': fix.get('rtk_status', 'RTK FIX'),
                    'time_wib': time_wib,
                    'easting': utm_e,
                    'northing': utm_n,
                    'utm_zone': f"{utm_zone}{utm_letter}",
                    'rot_x': rot_x,
                    'rot_y': rot_y,
                    'detected_slot': detected_slot
                })

        duration = 3.0
        target_count = None

        readings = gps_reader.collect_readings(duration=duration, target_count=target_count)
        if not readings:
            return jsonify({
                'error': f'Tidak ada data GPS valid dalam {duration} detik. '
                         f'Pastikan GPS receiver terhubung atau aktifkan mode simulasi.'
            }), 500

        avg = gps_parsing.average_nmea_data(readings)
        if not avg:
            return jsonify({
                'error': 'Tidak ada data fix GPS. Pastikan antena berada di tempat terbuka.'
            }), 500

        time_wib = datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=7))
        ).strftime('%Y-%m-%d %H:%M:%S WIB')

        # Hitung UTM Easting & Northing
        utm_e, utm_n, utm_zone, utm_letter = latlon_to_utm(
            float(avg['avg_lat']), float(avg['avg_lon'])
        )

        # Slot & Rotated coordinates dari counter.py
        detected_slot = None
        rot_x, rot_y = None, None
        if COUNTER_AVAILABLE:
            try:
                hasil_counter, rot_x, rot_y = counter.deteksi_blok(float(avg['avg_lon']), float(avg['avg_lat']))
                if hasil_counter:
                    detected_slot = hasil_counter[2]
            except Exception as ce:
                print(f"[WARN] Counter calculation failed: {ce}")

        return jsonify({
            'avg_lon': float(avg['avg_lon']),
            'avg_lat': float(avg['avg_lat']),
            'avg_alt': float(avg['avg_alt']),
            'count': int(avg['total_count']),
            'fix_count': int(avg['fix_count']),
            'used_fix_data': bool(avg['used_fix_data']),
            'avg_fix_quality': int(avg['avg_quality']),
            'avg_rtk_status': avg['avg_rtk_status'],
            'time_wib': time_wib,
            'easting': utm_e,
            'northing': utm_n,
            'utm_zone': f"{utm_zone}{utm_letter}",
            'rot_x': rot_x,
            'rot_y': rot_y,
            'detected_slot': detected_slot
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


HISTORY_FILE = os.path.join(os.path.dirname(__file__), "data_history.json")

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
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[WARN] Failed to save history file: {e}")


@app.route('/send-to-database', methods=['POST'])
def send_to_database():
    """
    Endpoint menerima data gabungan OCR + GPS, menyimpan ke file history JSON, dan log console.
    """
    try:
        payload = request.get_json(force=True)
        ocr_data  = payload.get('ocr_data', {})
        gps_data  = payload.get('gps_data', {})
        lokasi    = payload.get('lokasi', 'N/A')
        tipe_container = payload.get('tipe_container', 'N/A')
        image_uri = payload.get('image_uri', '')

        now_wib = datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=7))
        ).strftime('%Y-%m-%d %H:%M:%S WIB')

        record = {
            'id': int(time.time() * 1000),
            'tipe_container': tipe_container,
            'nomor_container': ocr_data.get('Nomor Container :', 'N/A'),
            'serial_number': ocr_data.get('Serial Number :', 'N/A'),
            'check_number': ocr_data.get('Check Number :', 'N/A'),
            'grade': ocr_data.get('Grade', 'N/A'),
            'lokasi_slot': lokasi,
            'waktu': gps_data.get('time_wib') or now_wib,
            'image_uri': image_uri
        }

        history = load_history()
        history.insert(0, record)
        save_history(history)

        print("\n" + "=" * 60)
        print("  DATA CONTAINER TERSIMPAN KE DATABASE")
        print("=" * 60)
        print(f"  Nomor Container : {record['nomor_container']}")
        print(f"  Tipe Container  : {record['tipe_container']}")
        print(f"  Lokasi Slot     : {record['lokasi_slot']}")
        print(f"  Waktu WIB       : {record['waktu']}")
        print("=" * 60 + "\n")

        return jsonify({'success': True, 'message': 'Data berhasil disimpan ke database.', 'record': record})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/save-record', methods=['POST'])
def api_save_record():
    """Endpoint langsung menyimpan record baru."""
    return send_to_database()


@app.route('/api/history', methods=['GET', 'DELETE'])
def api_history():
    """Endpoint membaca atau menghapus seluruh data riwayat."""
    if request.method == 'DELETE':
        save_history([])
        return jsonify({'success': True, 'message': 'Riwayat berhasil dibersihkan.'})
    
    history = load_history()
    return jsonify({'success': True, 'history': history, 'total': len(history)})


@app.route('/api/history/<int:record_id>', methods=['DELETE'])
def api_delete_history_item(record_id):
    """Endpoint menghapus 1 item record riwayat berdasarkan ID."""
    history = load_history()
    new_history = [item for item in history if str(item.get('id')) != str(record_id)]
    save_history(new_history)
    return jsonify({'success': True, 'message': 'Record riwayat berhasil dihapus.'})


@app.route('/api/history/delete-selected', methods=['POST'])
def api_delete_selected_history():
    """Endpoint menghapus beberapa item record riwayat terpilih."""
    data = request.json or {}
    raw_ids = data.get('ids', [])
    ids_to_delete = set(str(i) for i in raw_ids)
    
    history = load_history()
    new_history = [item for item in history if str(item.get('id')) not in ids_to_delete]
    save_history(new_history)
    return jsonify({'success': True, 'message': f'{len(ids_to_delete)} record berhasil dihapus.'})


@app.route('/api/export/<format_type>', methods=['GET'])
def api_export(format_type):
    """Export data riwayat ke format CSV atau JSON."""
    import io
    import csv

    history = load_history()
    
    if format_type.lower() in ('excel', 'xlsx', 'xls'):
        html_out = "<html><head><meta charset='utf-8'></head><body><table border='1'>"
        html_out += "<tr style='background-color:#1e293b;color:#ffffff;'><th>ID</th><th>Waktu WIB</th><th>Tipe Container</th><th>Nomor Container</th><th>Serial Number</th><th>Check Number</th><th>Grade</th><th>Lokasi Slot Depo</th></tr>"
        for item in history:
            html_out += f"<tr><td>{item.get('id','')}</td><td>{item.get('waktu','')}</td><td>{item.get('tipe_container','')}</td><td>{item.get('nomor_container','')}</td><td>{item.get('serial_number','')}</td><td>{item.get('check_number','')}</td><td>{item.get('grade','')}</td><td>{item.get('lokasi_slot','')}</td></tr>"
        html_out += "</table></body></html>"

        response = Response(html_out.encode('utf-8'), mimetype='application/vnd.ms-excel')
        response.headers['Content-Disposition'] = 'attachment; filename=riwayat_container_ocr.xls'
        return response

    elif format_type.lower() == 'json':
        clean_history = [{k: v for k, v in item.items() if k != 'image_uri'} for item in history]
        response = Response(
            json.dumps(clean_history, indent=2, ensure_ascii=False),
            mimetype='application/json'
        )
        response.headers['Content-Disposition'] = 'attachment; filename=riwayat_container_ocr.json'
        return response

    elif format_type.lower() == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        
        headers = [
            "ID", "Waktu WIB", "Tipe Container", "Nomor Container", 
            "Serial Number", "Check Number", "Grade", "Lokasi Slot Depo"
        ]
        writer.writerow(headers)

        for item in history:
            writer.writerow([
                item.get('id', ''),
                item.get('waktu', ''),
                item.get('tipe_container', ''),
                item.get('nomor_container', ''),
                item.get('serial_number', ''),
                item.get('check_number', ''),
                item.get('grade', ''),
                item.get('lokasi_slot', '')
            ])

        response = Response(output.getvalue(), mimetype='text/csv')
        response.headers['Content-Disposition'] = 'attachment; filename=riwayat_container_ocr.csv'
        return response

    return jsonify({'error': 'Format export tidak didukung (gunakan excel, csv, atau json).'}), 400


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if GPS_AVAILABLE:
        gps_reader.start()
        print("[GPS] Background GPS reader started.")
    else:
        print("[GPS] GPS reader not available — GPS features will show error in UI.")

    print("Server running at http://127.0.0.1:5000")
    try:
        app.run(debug=True, port=5000, threaded=True, use_reloader=False)
    finally:
        if GPS_AVAILABLE:
            gps_reader.stop()
            print("[GPS] Background GPS reader stopped.")
