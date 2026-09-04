from flask import Blueprint, jsonify, request, Response
import json
import time
from datetime import datetime, timedelta, timezone
from middleware.error_handler import APIError
from core.gps_utils import latlon_to_utm

gps_bp = Blueprint('gps', __name__)

try:
    from core import gps_reader
    from core import parsing as gps_parsing
    GPS_AVAILABLE = True
except ImportError:
    GPS_AVAILABLE = False

try:
    from utils import counter
    COUNTER_AVAILABLE = True
except ImportError:
    COUNTER_AVAILABLE = False

def require_gps():
    if not GPS_AVAILABLE:
        raise APIError('GPS module tidak tersedia.', 503)

@gps_bp.route('/current-status')
def current_status():
    """Lightweight polling endpoint untuk status GPS fix terkini (non-blocking)."""
    require_gps()
    try:
        status = gps_reader.get_current_fix()
        return jsonify(status)
    except Exception as e:
        raise APIError(str(e), 500)

@gps_bp.route('/live-location')
def live_location():
    """Endpoint real-time telemetri posisi rover terkini (lat/lon, UTM, slot, trail)."""
    require_gps()
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
        raise APIError(str(e), 500)

@gps_bp.route('/stream-gps')
def stream_gps():
    """Server-Sent Events (SSE) stream untuk update posisi rover secara langsung."""
    require_gps()

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

@gps_bp.route('/toggle-simulation', methods=['POST', 'GET'])
def toggle_simulation():
    """Aktifkan / matikan mode simulasi gerak rover."""
    require_gps()
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
        raise APIError(str(e), 500)

@gps_bp.route('/check-location')
def check_location():
    """
    Kumpulkan pembacaan GPS selama beberapa detik lalu kembalikan rata-rata.
    """
    require_gps()
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
            raise APIError(f'Tidak ada data GPS valid dalam {duration} detik. Pastikan GPS receiver terhubung atau aktifkan mode simulasi.', 500)

        avg = gps_parsing.average_nmea_data(readings)
        if not avg:
            raise APIError('Tidak ada data fix GPS. Pastikan antena berada di tempat terbuka.', 500)

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
    except APIError:
        raise
    except Exception as e:
        raise APIError(str(e), 500)
