"""
gps_reader.py
Background GPS reader — membuka port serial SEKALI dan terus membaca data
sehingga tidak ada konflik saat check-location dan current-status diakses bersamaan.
Mendukung telemetry real-time, jejak lintasan (trail), dan mode simulasi pergerakan rover.
"""
import time
import threading
import collections
import math
import pynmea2
import serial
from typing import Optional
from parsing import get_rtk_status, SERIAL_PORT, BAUDRATE

# ──────────────────────────────────────────────
# Buffer & Deque untuk Telemetri Real-Time
# ──────────────────────────────────────────────
_BUFFER_SIZE = 300
_lock = threading.Lock()
_readings_deque = collections.deque(maxlen=_BUFFER_SIZE)
_trail_deque = collections.deque(maxlen=100)  # Jejak lintasan pergerakan rover

# Mode Simulasi jika GPS fisik belum terhubung
_simulation_enabled = False

# Status fix terkini (telemetri lengkap)
_latest_fix = {
    'latitude': None,
    'longitude': None,
    'altitude': 0.0,
    'altitude_unit': 'M',
    'gps_quality': 0,
    'rtk_status': get_rtk_status(0),
    'num_sats': 0,
    'connected': False,
    'simulation': False,
    'utc_time': None,
    'ts': 0.0
}

# Kontrol thread
_thread = None          # type: Optional[threading.Thread]
_stop_event = threading.Event()
_connected = False


def set_simulation_mode(enabled=True):
    # type: (bool) -> bool
    """Aktifkan atau matikan mode simulasi pergerakan rover."""
    global _simulation_enabled
    with _lock:
        _simulation_enabled = bool(enabled)
        _latest_fix['simulation'] = _simulation_enabled
    print("[GPS-Reader] Simulation mode set to:", _simulation_enabled)
    return _simulation_enabled


def is_simulation_mode():
    # type: () -> bool
    """Cek apakah mode simulasi aktif."""
    with _lock:
        return _simulation_enabled


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


def _generate_simulated_step(step_idx):
    """Menghasilkan koordinat rover simulasi yang bergerak mengelilingi 6 titik survey yard."""
    waypoints = [
        (106.88178028, -6.11260706),  # P1
        (106.88190898, -6.11251261),  # P2
        (106.88187588, -6.11246944),  # P3
        (106.88189726, -6.11245381),  # P4
        (106.88185392, -6.11239707),  # P5
        (106.88170742, -6.11250445)   # P6
    ]
    num_wp = len(waypoints)
    sub_steps = 25  # jumlah langkah halus antar waypoint

    total_steps = num_wp * sub_steps
    curr_step = step_idx % total_steps

    wp_from = curr_step // sub_steps
    wp_to = (wp_from + 1) % num_wp
    t = (curr_step % sub_steps) / float(sub_steps)

    # Smooth cosine interpolation
    t_smooth = (1 - math.cos(t * math.pi)) / 2.0

    lon1, lat1 = waypoints[wp_from]
    lon2, lat2 = waypoints[wp_to]

    curr_lon = lon1 + (lon2 - lon1) * t_smooth
    curr_lat = lat1 + (lat2 - lat1) * t_smooth

    now_ts = time.time()
    return {
        'utc_time': time.strftime("%H:%M:%S", time.gmtime(now_ts)),
        'latitude': round(curr_lat, 8),
        'longitude': round(curr_lon, 8),
        'altitude': 12.5,
        'altitude_unit': 'M',
        'gps_quality': 4,  # RTK Fix
        'rtk_status': 'RTK FIX',
        'num_sats': 18,
        'ts': now_ts
    }


def _reader_thread_func():
    """Thread utama yang membaca serial terus-menerus atau mensimulasikan pergerakan."""
    global _connected, _latest_fix
    retry_delay = 2.0

    import os
    import glob

    sim_step = 0

    while not _stop_event.is_set():
        # Cek apakah mode simulasi diaktifkan secara eksplisit atau fallback
        with _lock:
            sim_active = _simulation_enabled

        if sim_active:
            reading = _generate_simulated_step(sim_step)
            sim_step += 1

            with _lock:
                _readings_deque.append(reading)
                _trail_deque.append({
                    'lat': reading['latitude'],
                    'lon': reading['longitude'],
                    'ts': reading['ts'],
                    'qual': reading['gps_quality']
                })

                _latest_fix = {
                    'latitude': reading['latitude'],
                    'longitude': reading['longitude'],
                    'altitude': reading['altitude'],
                    'altitude_unit': reading['altitude_unit'],
                    'gps_quality': reading['gps_quality'],
                    'rtk_status': reading['rtk_status'],
                    'num_sats': reading['num_sats'],
                    'connected': True,
                    'simulation': True,
                    'utc_time': reading['utc_time'],
                    'ts': reading['ts']
                }

            _stop_event.wait(0.3)  # update 3.3 Hz saat simulasi
            continue

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
                _latest_fix['simulation'] = False

            while not _stop_event.is_set():
                with _lock:
                    if _simulation_enabled:
                        break

                try:
                    raw = ser.readline()
                    line = raw.decode('ascii', errors='replace').strip()
                except serial.SerialException:
                    break  # port terputus, reconnect

                if not line:
                    continue

                if 'GGA' not in line or not line.startswith('$'):
                    continue

                reading = _parse_gga_line(line)
                if reading is None:
                    continue

                with _lock:
                    if reading.get('latitude') is not None and reading.get('longitude') is not None:
                        _readings_deque.append(reading)
                        _trail_deque.append({
                            'lat': reading['latitude'],
                            'lon': reading['longitude'],
                            'ts': reading['ts'],
                            'qual': reading['gps_quality']
                        })

                    now_ts = time.time()
                    while _readings_deque and (now_ts - _readings_deque[0].get('ts', now_ts)) > 30.0:
                        _readings_deque.popleft()

                    _latest_fix = {
                        'latitude': reading['latitude'],
                        'longitude': reading['longitude'],
                        'altitude': reading['altitude'],
                        'altitude_unit': reading['altitude_unit'],
                        'gps_quality': reading['gps_quality'],
                        'rtk_status': reading['rtk_status'],
                        'num_sats': reading['num_sats'],
                        'connected': True,
                        'simulation': False,
                        'utc_time': reading['utc_time'],
                        'ts': reading['ts']
                    }

        except serial.SerialException as e:
            _connected = False
            with _lock:
                _latest_fix['connected'] = False
            # Jika serial error dan belum simulasi, tunggu sebelum reconnect
            if not _stop_event.is_set():
                _stop_event.wait(retry_delay)
        except Exception as e:
            _connected = False
            with _lock:
                _latest_fix['connected'] = False
            print("[GPS-Reader] Unexpected error: {}".format(e))
            if not _stop_event.is_set():
                _stop_event.wait(retry_delay)
        finally:
            if ser and ser.is_open:
                try:
                    ser.close()
                except Exception:
                    pass

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


def get_trail():
    # type: () -> list
    """Kembalikan daftar titik histori pergerakan rover terkini."""
    with _lock:
        return list(_trail_deque)


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
            'connected': _connected,
            'simulation': _simulation_enabled
        }


def collect_readings(duration=2.0, target_count=None):
    # type: (float, Optional[int]) -> list
    """
    Kumpulkan pembacaan GPS real-time segar.
    """
    start_ts = time.time()

    while (time.time() - start_ts) < duration:
        if _stop_event.is_set():
            break
        with _lock:
            now_ts = time.time()
            fresh = [r for r in _readings_deque if (now_ts - r.get('ts', 0)) <= 4.0]
            fix_fresh = [r for r in fresh if r.get('gps_quality', 0) != 0]

            if len(fix_fresh) >= 5:
                if target_count is not None and target_count > 0 and len(fix_fresh) > target_count:
                    return fix_fresh[-target_count:]
                return fix_fresh

        time.sleep(0.1)

    with _lock:
        now_ts = time.time()
        fresh = [r for r in _readings_deque if (now_ts - r.get('ts', 0)) <= 4.0]

    if target_count is not None and target_count > 0 and len(fresh) > target_count:
        fresh = fresh[-target_count:]

    return fresh
