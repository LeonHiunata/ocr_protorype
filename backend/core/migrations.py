"""
core/migrations.py — Buat tabel di Supabase dan migrasi data dari JSON ke PostgreSQL.

Jalankan sekali:
    cd backend
    python core/migrations.py
"""

import os
import sys
import json

# Agar bisa dijalankan langsung dari folder backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))

from core.db import get_conn, release_conn

# ─── Lokasi file JSON lama ──────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(_BASE, '..', 'data')
USERS_FILE    = os.path.join(DATA_DIR, 'users.json')
HISTORY_FILE  = os.path.join(DATA_DIR, 'data_history.json')

# ─── DDL ────────────────────────────────────────────────────────────────────
CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'krani',
    status        TEXT NOT NULL DEFAULT 'pending'
);
"""

CREATE_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS container_history (
    id              BIGINT PRIMARY KEY,
    tipe_container  TEXT,
    nomor_container TEXT,
    serial_number   TEXT,
    check_number    TEXT,
    grade           TEXT,
    lokasi_slot     TEXT,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    altitude        DOUBLE PRECISION,
    easting         DOUBLE PRECISION,
    northing        DOUBLE PRECISION,
    utm_zone        TEXT,
    rtk_status      TEXT,
    waktu           TEXT,
    image_uri       TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
"""


def run_migrations():
    """Buat tabel jika belum ada. Dipanggil saat server start."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_USERS_TABLE)
            cur.execute(CREATE_HISTORY_TABLE)
        conn.commit()
        print("[DB] Tabel users & container_history siap.")
    except Exception as e:
        conn.rollback()
        print(f"[DB ERROR] Gagal membuat tabel: {e}")
        raise
    finally:
        release_conn(conn)


def migrate_users():
    """Migrasi data dari users.json ke tabel users (skip jika sudah ada)."""
    if not os.path.exists(USERS_FILE):
        print("[MIGRATE] users.json tidak ditemukan, lewati migrasi user.")
        return

    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        users_data = json.load(f)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            inserted = 0
            skipped  = 0
            for username, u in users_data.items():
                cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
                if cur.fetchone():
                    skipped += 1
                    continue
                cur.execute(
                    """
                    INSERT INTO users (username, password_hash, role, status)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (u['username'], u['password_hash'], u.get('role', 'krani'), u.get('status', 'pending'))
                )
                inserted += 1
        conn.commit()
        print(f"[MIGRATE] Users: {inserted} ditambahkan, {skipped} dilewati (sudah ada).")
    except Exception as e:
        conn.rollback()
        print(f"[MIGRATE ERROR] Gagal migrasi users: {e}")
        raise
    finally:
        release_conn(conn)


def migrate_history():
    """Migrasi data dari data_history.json ke tabel container_history (skip jika sudah ada)."""
    if not os.path.exists(HISTORY_FILE):
        print("[MIGRATE] data_history.json tidak ditemukan, lewati migrasi history.")
        return

    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        history = json.load(f)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            inserted = 0
            skipped  = 0
            for record in history:
                record_id = record.get('id')
                if not record_id:
                    continue
                cur.execute("SELECT 1 FROM container_history WHERE id = %s", (record_id,))
                if cur.fetchone():
                    skipped += 1
                    continue
                cur.execute(
                    """
                    INSERT INTO container_history
                        (id, tipe_container, nomor_container, serial_number,
                         check_number, grade, lokasi_slot,
                         latitude, longitude, altitude,
                         easting, northing, utm_zone, rtk_status,
                         waktu, image_uri)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        record_id,
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
                inserted += 1
        conn.commit()
        print(f"[MIGRATE] History: {inserted} record ditambahkan, {skipped} dilewati.")
    except Exception as e:
        conn.rollback()
        print(f"[MIGRATE ERROR] Gagal migrasi history: {e}")
        raise
    finally:
        release_conn(conn)


if __name__ == '__main__':
    print("=" * 60)
    print("  MIGRASI DATABASE KE SUPABASE POSTGRESQL")
    print("=" * 60)
    run_migrations()
    migrate_users()
    migrate_history()
    print("=" * 60)
    print("  SELESAI")
    print("=" * 60)
