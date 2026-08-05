import math
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from pyproj import Transformer

# ==========================
# KONFIGURASI SPASIAL & ROTASI
# ==========================
REF_LON = 106.88178028
REF_LAT = -6.11260706

ORIGIN_UTM_X = 708241.531
ORIGIN_UTM_Y = 9323986.322

SUDUT_ROTASI = 54.0 #rosi 53.83° agar polygon & grid tegak lurus ke utara
LEBAR_KOLOM = 6.0   # Lebar slot container (m - sumbu X, 2 kolom A & B)
PANJANG_BARIS = 3.0  # Tinggi slot container (m - sumbu Y, 6 baris 1 s/d 6)

JUMLAH_KOLOM = 12   # Jumlah kolom visualisasi
JUMLAH_BARIS = 8    # Jumlah baris visualisasi

# 6 Titik Boundary Survey
BOUNDARY_POINTS = [
    [106.88178028, -6.11260706],  # P1
    [106.88190898, -6.11251261],  # P2
    [106.88187588, -6.11246944],  # P3
    [106.88189726, -6.11245381],  # P4
    [106.88185392, -6.11239707],  # P5
    [106.88170742, -6.11250445]   # P6
]


def putar_titik(x, y, cx, cy, angle_deg):
    """
    Memutar titik (x, y) terhadap titik pusat (cx, cy) sebesar angle_deg.
    """
    angle_rad = math.radians(angle_deg)
    tx = x - cx
    ty = y - cy

    rx = tx * math.cos(angle_rad) - ty * math.sin(angle_rad)
    ry = tx * math.sin(angle_rad) + ty * math.cos(angle_rad)

    return rx + cx, ry + cy


def deteksi_blok(lon, lat, angle_deg=SUDUT_ROTASI):
    """
    Mengonversi koordinat WGS84 (lon, lat) ke UTM 48S (EPSG:32748),
    memutar posisi relatif terhadap origin, dan menentukan slot container.
    """
    transformer = Transformer.from_crs(
        "EPSG:4326",
        "EPSG:32748",
        always_xy=True
    )

    utm_x, utm_y = transformer.transform(lon, lat)

    rot_x, rot_y = putar_titik(
        utm_x,
        utm_y,
        ORIGIN_UTM_X,
        ORIGIN_UTM_Y,
        angle_deg
    )

    jarak_x = rot_x - ORIGIN_UTM_X
    jarak_y = rot_y - ORIGIN_UTM_Y

    if jarak_x < 0 or jarak_y < 0:
        return None, rot_x, rot_y

    indeks_kolom = int(jarak_x // LEBAR_KOLOM)
    indeks_baris = int(jarak_y // PANJANG_BARIS)

    huruf = chr(65 + indeks_baris)
    angka = indeks_kolom + 1

    return (
        (indeks_baris, indeks_kolom, f"{huruf}{angka}"),
        rot_x,
        rot_y
    )


def gambar_grid(rot_x, rot_y, blok_info):
    """
    Menggambar grid visualisasi slot container dengan matplotlib.
    """
    fig, ax = plt.subplots(figsize=(12, 8))

    # Gambar grid
    for baris in range(JUMLAH_BARIS):
        for kolom in range(JUMLAH_KOLOM):
            x = kolom * LEBAR_KOLOM
            y = baris * PANJANG_BARIS

            warna = "#f97316"  # Oranye

            if blok_info is not None:
                if baris == blok_info[0] and kolom == blok_info[1]:
                    warna = "#10b981"  # Hijau / Gold untuk terpilih

            rect = Rectangle(
                (x, y),
                LEBAR_KOLOM,
                PANJANG_BARIS,
                facecolor=warna,
                edgecolor="black",
                alpha=0.8
            )

            ax.add_patch(rect)

            label = f"{chr(65+baris)}{kolom+1}"
            ax.text(
                x + LEBAR_KOLOM / 2,
                y + PANJANG_BARIS / 2,
                label,
                ha='center',
                va='center',
                fontsize=8,
                color="white",
                weight="bold"
            )

    # Posisi titik GPS
    px = rot_x - ORIGIN_UTM_X
    py = rot_y - ORIGIN_UTM_Y

    ax.scatter(
        px,
        py,
        color="red",
        s=120,
        zorder=5,
        label="Posisi GPS"
    )

    ax.text(
        px,
        py + 0.5,
        "GPS",
        color="red",
        weight="bold"
    )

    ax.set_xlim(0, JUMLAH_KOLOM * LEBAR_KOLOM)
    ax.set_ylim(0, JUMLAH_BARIS * PANJANG_BARIS)
    ax.set_aspect("equal")

    ax.set_xlabel("Meter (X)")
    ax.set_ylabel("Meter (Y)")
    ax.set_title("Visualisasi Grid Container Yard (Rotasi 54°)")
    ax.grid(True)

    plt.legend()
    plt.show()


if __name__ == "__main__":
    print("=== Program Deteksi Container (OCR Prototype) ===")
    try:
        input_lon = float(input("Longitude : "))
        input_lat = float(input("Latitude  : "))

        hasil, rot_x, rot_y = deteksi_blok(input_lon, input_lat)

        if hasil is None:
            print("Titik berada di luar area container.")
        else:
            print(f"Container berada di Slot: {hasil[2]}")

        gambar_grid(rot_x, rot_y, hasil)
    except KeyboardInterrupt:
        print("\nSelesai.")
