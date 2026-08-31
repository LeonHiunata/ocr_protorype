import time
import serial
import pynmea2
import csv
from datetime import datetime, timedelta, timezone

# --- KONFIGURASI ---
SERIAL_PORT = '/dev/ttyACM0'
BAUDRATE = 115200
DURASI_DETIK = 5  # Durasi pengambilan data
TARGET_READINGS = 30  # Target jumlah pembacaan untuk rata-rata
NAMA_FILE = 'data_gps_30detik.csv'

def get_rtk_status(gps_qual):
    """Mengubah kode kualitas GPS NMEA menjadi status yang mudah dibaca"""
    status_map = {
        0: "Fix Not Available (Tidak ada sinyal)",
        1: "GPS Fix (Single/SPS)",
        2: "Differential GPS Fix (DGPS)",
        3: "PPS Fix",
        4: "RTK Fix (Sangat Akurat)",
        5: "RTK Float (Sedang Convergence)",
        6: "Estimated / Dead Reckoning",
        8: "Simulation Mode"
    }
    return status_map.get(gps_qual, f"Unknown ({gps_qual})")

def debug_nmea_stream(serial_port=SERIAL_PORT, baudrate=BAUDRATE, timeout_seconds=10):
    """Debug function untuk melihat raw NMEA sentences dari receiver"""
    ser = None
    start = time.time()
    gga_count = 0
    other_count = 0
    print(f"\n[DEBUG] Membaca NMEA stream selama {timeout_seconds} detik dari {serial_port}...")
    try:
        ser = serial.Serial(serial_port, baudrate=baudrate, timeout=1)
        while (time.time() - start) < timeout_seconds:
            line = ser.readline().decode('ascii', errors='replace').strip()
            if not line:
                continue
            
            if line.startswith('$GN') or line.startswith('$GP'):
                if 'GGA' in line:
                    gga_count += 1
                    print(f"  [GGA #{gga_count}] {line[:100]}")
                    try:
                        msg = pynmea2.parse(line)
                        qual = getattr(msg, 'gps_qual', None)
                        print(f"    -> Quality: {qual}, Lat: {msg.latitude}, Lon: {msg.longitude}")
                    except Exception as e:
                        print(f"    -> Parse error: {e}")
                else:
                    other_count += 1
                    if other_count <= 10:
                        print(f"  [{line[1:4]}] {line[:80]}")
        print(f"\n[DEBUG] Selesai: {gga_count} GGA, {other_count} lainnya\n")
    except serial.SerialException as e:
        print(f"[DEBUG] Serial error: {e}")
    finally:
        if ser and ser.is_open:
            ser.close()

def convert_utc_to_wib(utc_time_obj):
    """Mengonversi objek datetime.time (UTC dari GPS) ke string format WIB"""
    if utc_time_obj is None:
        return "-"
    
    # Ambil tanggal hari ini untuk digabungkan dengan waktu UTC dari GPS
    today = datetime.now(timezone.utc).date()
    utc_datetime = datetime.combine(today, utc_time_obj, tzinfo=timezone.utc)
    
    # Konversi UTC ke WIB (UTC + 7 jam)
    wib_timezone = timezone(timedelta(hours=7))
    wib_datetime = utc_datetime.astimezone(wib_timezone)
    
    return wib_datetime.strftime("%H:%M:%S WIB")

def average_nmea_data(readings):
    """Hitung rata-rata latitude, longitude, altitude, dan status dari daftar pembacaan.
    Jika ada pembacaan dengan fix GPS (gps_quality != 0), rata-rata akan dihitung dari pembacaan fix tersebut.
    Jika tidak ada pembacaan fix, rata-rata akan dihitung dari semua pembacaan yang tersedia sebagai fallback.
    """
    if not readings:
        return None

    fix_readings = [r for r in readings if r.get('gps_quality', 0) != 0]
    
    # Hanya gunakan data fix. Jika tidak ada, kembalikan None.
    if not fix_readings:
        return None

    source = fix_readings

    avg_lat = sum(r['latitude'] for r in source) / len(source)
    avg_lon = sum(r['longitude'] for r in source) / len(source)
    avg_alt = sum(r['altitude'] for r in source) / len(source)
    avg_quality = max(r['gps_quality'] for r in source) if source else 0
    avg_status = get_rtk_status(avg_quality)

    return {
        'avg_lat': avg_lat,
        'avg_lon': avg_lon,
        'avg_alt': avg_alt,
        'total_count': len(readings),
        'fix_count': len(fix_readings),
        'used_fix_data': True,
        'avg_quality': avg_quality,
        'avg_rtk_status': avg_status
    }


def save_nmea_csv(readings, filename=NAMA_FILE):
    if not readings:
        return
    keys = readings[0].keys()
    with open(filename, 'w', newline='', encoding='utf-8') as output_file:
        dict_writer = csv.DictWriter(output_file, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(readings)


def capture_nmea_data(serial_port=SERIAL_PORT, baudrate=BAUDRATE, duration=DURASI_DETIK, target_count=TARGET_READINGS):
    """Ambil data NMEA selama durasi tertentu dan hitung rata-rata dari pembacaan terakhir."""
    start_time = time.time()
    readings = []
    ser = None
    import os, glob

    try:
        while (time.time() - start_time) < duration:
            if ser is None or not ser.is_open:
                try:
                    port_to_try = serial_port
                    if not os.path.exists(port_to_try):
                        possible_ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
                        if possible_ports:
                            port_to_try = possible_ports[0]
                    ser = serial.Serial(port_to_try, baudrate=baudrate, timeout=1)
                except serial.SerialException:
                    time.sleep(0.5)
                    continue

            try:
                line = ser.readline().decode('ascii', errors='replace').strip()
            except serial.SerialException:
                if ser:
                    ser.close()
                ser = None
                continue

            if line.startswith('$GNGGA') or line.startswith('$GPGGA'):
                try:
                    msg = pynmea2.parse(line)

                    # --- Ambil latitude & longitude ---
                    lat = msg.latitude
                    lon = msg.longitude

                    # --- Ambil altitude dengan aman (bisa None atau string kosong '') ---
                    alt_raw = msg.altitude
                    try:
                        alt = float(alt_raw) if alt_raw not in (None, '') else 0.0
                    except (TypeError, ValueError):
                        alt = 0.0

                    # --- Ambil GPS quality ---
                    gps_qual = getattr(msg, 'gps_qual', None)
                    try:
                        gps_qual_int = int(gps_qual) if gps_qual not in (None, '') else 0
                    except (TypeError, ValueError):
                        gps_qual_int = 0

                    # --- Validasi koordinat: pastikan bukan None, bukan string kosong, bukan 0,0 ---
                    try:
                        lat_f = float(lat) if lat not in (None, '') else None
                        lon_f = float(lon) if lon not in (None, '') else None
                    except (TypeError, ValueError):
                        lat_f = None
                        lon_f = None

                    if lat_f is not None and lon_f is not None and not (lat_f == 0.0 and lon_f == 0.0):
                        readings.append({
                            'utc_time': msg.timestamp.isoformat() if msg.timestamp else None,
                            'latitude': lat_f,
                            'longitude': lon_f,
                            'altitude': alt,
                            'altitude_unit': msg.altitude_units if msg.altitude_units else 'M',
                            'gps_quality': gps_qual_int,
                            'rtk_status': get_rtk_status(gps_qual_int)
                        })
                except pynmea2.ParseError:
                    continue
                except Exception as e:
                    # Log error tapi jangan buang data lain
                    print(f"[WARN] Gagal parse GGA line: {e} | Line: {line[:80]}")
                    continue

            time.sleep(0.05)

        if not readings:
            return []

        if target_count is not None and target_count > 0 and len(readings) > target_count:
            readings = readings[-target_count:]

        save_nmea_csv(readings)
        return readings
    finally:
        if ser and ser.is_open:
            ser.close()


def read_current_fix(serial_port=SERIAL_PORT, baudrate=BAUDRATE, timeout_seconds=2):
    """Baca singkat dari serial untuk mendapatkan status fix terkini.
    Mengembalikan dict: { 'gps_quality': int, 'rtk_status': str, 'num_sats': int }
    """
    ser = None
    start = time.time()
    last = {'gps_quality': 0, 'rtk_status': get_rtk_status(0), 'num_sats': 0}
    try:
        ser = serial.Serial(serial_port, baudrate=baudrate, timeout=1)
        while (time.time() - start) < timeout_seconds:
            line = ser.readline().decode('ascii', errors='replace').strip()
            if line.startswith('$GNGGA') or line.startswith('$GPGGA'):
                try:
                    msg = pynmea2.parse(line)
                    gps_qual = getattr(msg, 'gps_qual', None)
                    try:
                        gps_qual_int = int(gps_qual) if gps_qual not in (None, '') else 0
                    except (TypeError, ValueError):
                        gps_qual_int = 0

                    num_sats = 0
                    try:
                        num_sats = int(getattr(msg, 'num_sats', 0) or 0)
                    except (TypeError, ValueError):
                        num_sats = 0

                    last = {
                        'gps_quality': gps_qual_int,
                        'rtk_status': get_rtk_status(gps_qual_int),
                        'num_sats': num_sats
                    }

                    # If we already have a valid fix, return early
                    if gps_qual_int != 0:
                        return last
                except (pynmea2.ParseError, AttributeError, ValueError):
                    continue
            time.sleep(0.05)
        return last
    finally:
        if ser and ser.is_open:
            ser.close()

def main():
    print(f"--- Menghubungkan ke ZED-F9P di {SERIAL_PORT} ({BAUDRATE} baud)... ---")
    
    import os, glob
    ser = None
    data_terkumpul = []
    waktu_mulai = time.time()
    
    try:
        print(f"Mulai mengambil data selama {DURASI_DETIK} detik...\n")
        
        while (time.time() - waktu_mulai) < DURASI_DETIK:
            sisa_waktu = int(DURASI_DETIK - (time.time() - waktu_mulai))
            
            if ser is None or not ser.is_open:
                try:
                    port_to_try = SERIAL_PORT
                    if not os.path.exists(port_to_try):
                        possible_ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
                        if possible_ports:
                            port_to_try = possible_ports[0]
                    ser = serial.Serial(port_to_try, baudrate=BAUDRATE, timeout=1)
                    print(f"[{sisa_waktu}s tersisa] Terhubung ke {port_to_try}!")
                except serial.SerialException:
                    print(f"[{sisa_waktu}s tersisa] Menunggu perangkat GPS...")
                    time.sleep(1)
                    continue

            try:
                line = ser.readline().decode('ascii', errors='replace').strip()
            except serial.SerialException:
                print(f"[{sisa_waktu}s tersisa] Koneksi terputus, mencoba menyambung ulang...")
                if ser:
                    ser.close()
                ser = None
                continue
            
            # Memastikan baris berisi data GNGGA atau GPGGA
            if line.startswith('$GNGGA') or line.startswith('$GPGGA'):
                try:
                    # Parsing string NMEA
                    msg = pynmea2.parse(line)
                    
                    # Mengambil data yang dibutuhkan
                    lat = msg.latitude
                    lon = msg.longitude
                    alt = msg.altitude
                    alt_unit = msg.altitude_units if msg.altitude_units else "M"
                    rtk_code = msg.gps_qual
                    rtk_status = get_rtk_status(rtk_code)
                    
                    # Konversi waktu UTC satelit ke WIB
                    waktu_gps_wib = convert_utc_to_wib(msg.timestamp)
                    # Waktu lokal komputer saat ini (WIB)
                    waktu_lokal_wib = datetime.now().strftime("%Y-%m-%d %H:%M:%S WIB")
                    
                    # Hanya simpan jika koordinat tidak kosong
                    if lat and lon:
                        row_data = {
                            "Waktu Lokal (WIB)": waktu_lokal_wib,
                            "Waktu GPS (WIB)": waktu_gps_wib,
                            "Latitude": f"{lat:.8f}",
                            "Longitude": f"{lon:.8f}",
                            "Altitude": alt,
                            "Satuan Altitude": alt_unit,
                            "RTK Status": rtk_status
                        }
                        data_terkumpul.append(row_data)
                        
                        # Tampilkan realtime log di terminal
                        print(f"[{sisa_waktu}s tersisa] {waktu_lokal_wib} -> Lat: {lat:.8f}, Lon: {lon:.8f}, Status: {rtk_status}")
                    else:
                        print(f"[{sisa_waktu}s tersisa] Mengambil data... (Satelit belum fix/koordinat kosong)")
                        
                except pynmea2.ParseError:
                    pass # Abaikan data korup ringan di serial
                except AttributeError:
                    pass
                    
            time.sleep(0.05)
            
        # --- PROSES PEMBUATAN EXCEL (CSV) ---
        print(f"\nDurasi {DURASI_DETIK} detik selesai. Memulai pembuatan file...")
        
        if data_terkumpul:
            keys = data_terkumpul[0].keys()
            with open(NAMA_FILE, 'w', newline='', encoding='utf-8') as output_file:
                dict_writer = csv.DictWriter(output_file, fieldnames=keys)
                dict_writer.writeheader()
                dict_writer.writerows(data_terkumpul)
                
            print(f"✓ Berhasil! {len(data_terkumpul)} data tersimpan di file: {NAMA_FILE}")
            print("Kamu bisa langsung membukanya di Excel / LibreOffice Calc.")
        else:
            print(f"❌ Gagal menyimpan: Tidak ada data koordinat valid selama {DURASI_DETIK} detik.")
            
    except KeyboardInterrupt:
        print("\nProgram dihentikan paksa oleh pengguna.")
    finally:
        if ser and getattr(ser, 'is_open', False):
            ser.close()

if __name__ == "__main__":
    main()