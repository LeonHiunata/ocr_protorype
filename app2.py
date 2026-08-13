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
    return render_template("index2.html")

@app.route("/process", methods=["POST"])
def process():
    global _last_ocr_data

    if "file" not in request.files:
        return render_template("index2.html", error="No file uploaded.")

    file = request.files["file"]

    if file.filename == "":
        return render_template("index2.html", error="No selected file.")

    try:
        try:
            tolerance = int(request.form.get("tolerance", 150))
        except ValueError:
            tolerance = 150

        image_bytes = file.read()
        annotated_img, extracted_data = process_pipeline(image_bytes, x_tolerance=tolerance)

        if annotated_img is None:
            return render_template("index2.html", error="Failed to process image.")

        _last_ocr_data = extracted_data

        annotated_bgr = cv2.cvtColor(annotated_img, cv2.COLOR_RGB2BGR)
        _, buffer = cv2.imencode('.jpg', annotated_bgr)
        encoded_image = base64.b64encode(buffer).decode('utf-8')
        image_data_uri = f"data:image/jpeg;base64,{encoded_image}"

        return render_template(
            "index2.html",
            image_uri=image_data_uri,
            results=extracted_data,
            tolerance=tolerance,
            gps_available=GPS_AVAILABLE
        )

    except Exception as e:
        return render_template("index2.html", error=f"An error occurred: {str(e)}")

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

        utm_e, utm_n, utm_zone, utm_letter = latlon_to_utm(
            float(avg['avg_lat']), float(avg['avg_lon'])
        )

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
            'utm_zone': f"{utm_zone}{utm_letter}"
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/send-to-database', methods=['POST'])
def send_to_database():
    """
    Placeholder endpoint: menerima data gabungan OCR + GPS dan mencetak ke console.
    """
    try:
        payload = request.get_json(force=True)
        ocr_data  = payload.get('ocr_data', {})
        gps_data  = payload.get('gps_data', {})
        lokasi    = payload.get('lokasi', 'N/A')

        print("\n" + "=" * 60)
        print("  SEND TO DATABASE — DATA GABUNGAN OCR + GPS (FILE INPUT)")
        print("=" * 60)
        print(f"  Nomor Container : {ocr_data.get('Nomor Container :', 'N/A')}")
        print(f"  Serial Number   : {ocr_data.get('Serial Number :', 'N/A')}")
        print(f"  Check Number    : {ocr_data.get('Check Number :', 'N/A')}")
        print(f"  Grade           : {ocr_data.get('Grade', 'N/A')}")
        print(f"  Lokasi Slot     : {lokasi}")
        print("-" * 60)
        print(f"  Latitude        : {gps_data.get('avg_lat') or gps_data.get('latitude', 'N/A')}")
        print(f"  Longitude       : {gps_data.get('avg_lon') or gps_data.get('longitude', 'N/A')}")
        print(f"  Altitude        : {gps_data.get('avg_alt') or gps_data.get('altitude', 'N/A')} m")
        print(f"  Easting  (UTM)  : {gps_data.get('easting', 'N/A')} m")
        print(f"  Northing (UTM)  : {gps_data.get('northing', 'N/A')} m")
        print(f"  UTM Zone        : {gps_data.get('utm_zone', 'N/A')}")
        print(f"  RTK Status      : {gps_data.get('avg_rtk_status') or gps_data.get('rtk_status', 'N/A')}")
        print(f"  GPS Quality     : {gps_data.get('avg_fix_quality') or gps_data.get('gps_quality', 'N/A')}")
        print(f"  Waktu WIB       : {gps_data.get('time_wib', 'N/A')}")
        print("=" * 60 + "\n")

        return jsonify({'success': True, 'message': 'Data dicetak ke console (placeholder).'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if GPS_AVAILABLE:
        gps_reader.start()
        print("[GPS] Background GPS reader started.")
    else:
        print("[GPS] GPS reader not available — GPS features will show error in UI.")

    print("Server running at http://127.0.0.1:5001")
    try:
        app.run(debug=True, port=5001, threaded=True, use_reloader=False)
    finally:
        if GPS_AVAILABLE:
            gps_reader.stop()
            print("[GPS] Background GPS reader stopped.")
