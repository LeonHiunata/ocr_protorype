import math

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
