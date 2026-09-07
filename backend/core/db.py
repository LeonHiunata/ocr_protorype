"""
core/db.py — Central database connection pool for PostgreSQL (Supabase).

Usage:
    from core.db import get_conn, release_conn

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ...")
            rows = cur.fetchall()
        conn.commit()
    finally:
        release_conn(conn)
"""

import os
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL tidak ditemukan di .env. Pastikan sudah diset.")

# Connection pool: min 1, max 10 connections
# sslmode=require diperlukan untuk Supabase
_pool = pool.SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    dsn=DATABASE_URL + "?sslmode=require",
)


def get_conn():
    """Ambil koneksi dari pool."""
    return _pool.getconn()


def release_conn(conn):
    """Kembalikan koneksi ke pool."""
    if conn:
        _pool.putconn(conn)
