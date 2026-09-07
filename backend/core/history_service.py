"""
core/history_service.py — Baca & tulis riwayat container via PostgreSQL (Supabase).

API publik yang dipertahankan:
    load_history()          -> list[dict]   (diurutkan terbaru di atas)
    save_history(data)      -> None         (gantikan seluruh tabel — dipakai DELETE ALL)
    save_record(record)     -> None         (insert/update satu record)
    delete_record(id)       -> None
    delete_records(ids)     -> None
"""

from core.db import get_conn, release_conn

# Kolom yang dikembalikan ke frontend (sesuai format JSON lama)
_COLUMNS = (
    'id', 'tipe_container', 'nomor_container', 'serial_number',
    'check_number', 'grade', 'lokasi_slot',
    'latitude', 'longitude', 'altitude',
    'easting', 'northing', 'utm_zone', 'rtk_status',
    'waktu', 'image_uri',
)


def _row_to_dict(row: tuple) -> dict:
    return dict(zip(_COLUMNS, row))


def load_history() -> list:
    """Return semua record, diurutkan terbaru di atas."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM container_history ORDER BY id DESC"
            )
            rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        print(f"[WARN] Gagal membaca history: {e}")
        return []
    finally:
        release_conn(conn)


def save_record(record: dict):
    """Insert satu record baru. Jika id sudah ada, diabaikan (ON CONFLICT DO NOTHING)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO container_history
                    (id, tipe_container, nomor_container, serial_number,
                     check_number, grade, lokasi_slot,
                     latitude, longitude, altitude,
                     easting, northing, utm_zone, rtk_status,
                     waktu, image_uri)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    record.get('id'),
                    record.get('tipe_container'),
                    record.get('nomor_container'),
                    record.get('serial_number'),
                    record.get('check_number'),
                    record.get('grade'),
                    record.get('lokasi_slot'),
                    record.get('latitude'),
                    record.get('longitude'),
                    record.get('altitude'),
                    record.get('easting'),
                    record.get('northing'),
                    record.get('utm_zone'),
                    record.get('rtk_status'),
                    record.get('waktu'),
                    record.get('image_uri'),
                )
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[WARN] Gagal menyimpan record: {e}")
    finally:
        release_conn(conn)


def save_history(data: list):
    """
    Ganti seluruh isi tabel dengan `data`.
    Dipakai oleh endpoint DELETE ALL (/api/history DELETE).
    Jika data = [], hanya hapus semua record.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM container_history")
            for record in data:
                cur.execute(
                    """
                    INSERT INTO container_history
                        (id, tipe_container, nomor_container, serial_number,
                         check_number, grade, lokasi_slot,
                         latitude, longitude, altitude,
                         easting, northing, utm_zone, rtk_status,
                         waktu, image_uri)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        record.get('id'),
                        record.get('tipe_container'),
                        record.get('nomor_container'),
                        record.get('serial_number'),
                        record.get('check_number'),
                        record.get('grade'),
                        record.get('lokasi_slot'),
                        record.get('latitude'),
                        record.get('longitude'),
                        record.get('altitude'),
                        record.get('easting'),
                        record.get('northing'),
                        record.get('utm_zone'),
                        record.get('rtk_status'),
                        record.get('waktu'),
                        record.get('image_uri'),
                    )
                )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[WARN] Gagal save_history: {e}")
    finally:
        release_conn(conn)


def delete_record(record_id):
    """Hapus satu record berdasarkan id."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM container_history WHERE id = %s", (str(record_id),))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[WARN] Gagal delete record {record_id}: {e}")
    finally:
        release_conn(conn)


def delete_records(ids: list):
    """Hapus beberapa record sekaligus."""
    if not ids:
        return
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM container_history WHERE id::TEXT = ANY(%s)",
                ([str(i) for i in ids],)
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[WARN] Gagal delete records: {e}")
    finally:
        release_conn(conn)
