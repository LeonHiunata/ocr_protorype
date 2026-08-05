"""
gps_reader.py
Background GPS reader — membuka port serial SEKALI dan terus membaca data
sehingga tidak ada konflik saat check-location dan current-status diakses bersamaan.
"""
import time
import threading
import collections
import pynmea2
import serial
from typing import Optional
from parsing import get_rtk_status, SERIAL_PORT, BAUDRATE

# ──────────────────────────────────────────────
# Ring buffer untuk menyimpan pembacaan GGA valid
# ──────────────────────────────────────────────
_BUFFER_SIZE = 100          # simpan max 300 pembacaan terakhir
_lock = threading.Lock()
_readings_deque = collections.deque(maxlen=_BUFFER_SIZE)

# Status fix terkini (untuk endpoint /current-status)
_latest_fix = {
    'gps_quality': 0,
    'rtk_status': get_rtk_status(0),
    'num_sats': 0,
    'connected': False
}

# Kontrol thread
_thread = None          # type: Optional[threading.Thread]
_stop_event = threading.Event()
_connected = False


def _parse_gga_line(line):
    # type: (str) -> Optional[dict]
    """Parse satu baris NMEA GGA. Return dict pembacaan atau None jika tidak valid."""
    try:
        msg = pynmea2.parse(line)

        lat = msg.latitude
        lon = msg.longitude

        alt_raw = msg.altitude
        try:
            alt = float(alt_raw) if alt_raw not in (None, '') else 0.0
        except (TypeError, ValueError):
            alt = 0.0

        gps_qual = getattr(msg, 'gps_qual', None)
        try:
            gps_qual_int = int(gps_qual) if gps_qual not in (None, '') else 0
        except (TypeError, ValueError):
            gps_qual_int = 0

        try:
            lat_f = float(lat) if lat not in (None, '') else None
            lon_f = float(lon) if lon not in (None, '') else None
        except (TypeError, ValueError):
            lat_f = None
            lon_f = None

        if lat_f == 0.0 and lon_f == 0.0:
            lat_f = None
            lon_f = None

        num_sats = 0
        try:
            num_sats = int(getattr(msg, 'num_sats', 0) or 0)
        except (TypeError, ValueError):
            num_sats = 0

        return {
            'utc_time': msg.timestamp.isoformat() if msg.timestamp else None,
            'latitude': lat_f,
            'longitude': lon_f,
            'altitude': alt,
            'altitude_unit': msg.altitude_units if msg.altitude_units else 'M',
            'gps_quality': gps_qual_int,
            'rtk_status': get_rtk_status(gps_qual_int),
            'num_sats': num_sats,
            'ts': time.time()          # timestamp lokal saat data diterima
        }
    except Exception:
        return None


def _reader_thread_func():
    """Thread utama yang membaca serial terus-menerus."""
    global _connected, _latest_fix
    retry_delay = 2.0

    import os
    import glob

    while not _stop_event.is_set():
        ser = None
        try:
            port_to_try = SERIAL_PORT
            if not os.path.exists(port_to_try):
                possible_ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
                if possible_ports:
                    port_to_try = possible_ports[0]

            ser = serial.Serial(port_to_try, baudrate=BAUDRATE, timeout=1)
            _connected = True
            print("[GPS-Reader] Terhubung ke {} @ {} baud".format(port_to_try, BAUDRATE))

            with _lock:
                _latest_fix['connected'] = True

            gga_received = 0
            gga_filtered = 0

            while not _stop_event.is_set():
                try:
                    raw = ser.readline()
                    line = raw.decode('ascii', errors='replace').strip()
                except serial.SerialException:
                    break  # port terputus, reconnect

                if not line:
                    continue

                # Terima semua varian GGA: $GNGGA, $GPGGA, $GLGGA, $GAGGA, $GBGGA, dll.
                if 'GGA' not in line:
                    continue

                # Pastikan ini NMEA sentence yang valid (diawali $)
                if not line.startswith('$'):
                    continue

                reading = _parse_gga_line(line)
                if reading is None:
                    # GGA diterima tapi tidak valid (parse error)
                    continue

                with _lock:
                    if reading.get('latitude') is not None and reading.get('longitude') is not None:
                        _readings_deque.append(reading)
                    
                    # Auto-purge data yang lebih tua dari 5.0 detik
                    now_ts = time.time()
                    while _readings_deque and (now_ts - _readings_deque[0].get('ts', now_ts)) > 5.0:
                        _readings_deque.popleft()

                    _latest_fix = {
                        'gps_quality': reading['gps_quality'],
                        'rtk_status': reading['rtk_status'],
                        'num_sats': reading['num_sats'],
                        'connected': True
                    }

        except serial.SerialException as e:
            _connected = False
            with _lock:
                _latest_fix['connected'] = False
            print("[GPS-Reader] Serial error: {} — reconnect dalam {}s".format(e, retry_delay))
        except Exception as e:
            _connected = False
            with _lock:
                _latest_fix['connected'] = False
            print("[GPS-Reader] Unexpected error: {}".format(e))
        finally:
            if ser and ser.is_open:
                try:
                    ser.close()
                except Exception:
                    pass

        # Tunggu sebelum reconnect
        if not _stop_event.is_set():
            _stop_event.wait(retry_delay)

    _connected = False
    print("[GPS-Reader] Thread berhenti.")


def start():
    """Mulai background reader thread (idempotent)."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_reader_thread_func, daemon=True, name="GPS-Reader")
    _thread.start()


def stop():
    """Hentikan background reader thread."""
    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)


def get_current_fix():
    # type: () -> dict
    """Kembalikan status fix GPS terkini (non-blocking, thread-safe)."""
    with _lock:
        return dict(_latest_fix)


def get_buffer_info():
    # type: () -> dict
    """Kembalikan info diagnostik buffer untuk debugging."""
    with _lock:
        total = len(_readings_deque)
        fix_count = sum(1 for r in _readings_deque if r.get('gps_quality', 0) != 0)
        oldest_age = None
        newest_age = None
        now = time.time()
        if _readings_deque:
            oldest_age = round(now - _readings_deque[0].get('ts', now), 1)
            newest_age = round(now - _readings_deque[-1].get('ts', now), 1)
        return {
            'buffer_total': total,
            'buffer_fix_count': fix_count,
            'oldest_reading_age_sec': oldest_age,
            'newest_reading_age_sec': newest_age,
            'connected': _connected
        }


def collect_readings(duration=2.0, target_count=None):
    # type: (float, Optional[int]) -> list
    """
    Kumpulkan pembacaan GPS real-time segar (usia < 4 detik).
    Langsung mengembalikan segera setelah 5+ data fix segar terkumpul,
    sehingga tidak menunggu durasi secara sia-sia atau memakai data lama.
    """
    start_ts = time.time()

    # Loop tunggu data segar (max durasi detik)
    while (time.time() - start_ts) < duration:
        if _stop_event.is_set():
            break
        with _lock:
            now_ts = time.time()
            # Hanya ambil pembacaan yang kurang dari 4 detik
            fresh = [r for r in _readings_deque if (now_ts - r.get('ts', 0)) <= 4.0]
            fix_fresh = [r for r in fresh if r.get('gps_quality', 0) != 0]

            if len(fix_fresh) >= 5:
                if target_count is not None and target_count > 0 and len(fix_fresh) > target_count:
                    return fix_fresh[-target_count:]
                return fix_fresh

        time.sleep(0.1)

    # Ambil data segar terkini yang ada (< 4 detik)
    with _lock:
        now_ts = time.time()
        fresh = [r for r in _readings_deque if (now_ts - r.get('ts', 0)) <= 4.0]

    if target_count is not None and target_count > 0 and len(fresh) > target_count:
        fresh = fresh[-target_count:]

    return fresh
