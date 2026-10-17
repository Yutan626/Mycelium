"""Small local gazetteer for family-history place names.

Maps common ``"City, Country"`` strings (and bare city or country names) to
``(latitude, longitude)`` tuples at city-level precision (one decimal place,
suitable for globe markers — not for navigation).

Matching rules (deliberately conservative):

* Matching ignores case and extra whitespace.
* A full ``"city, country"`` string is tried first, then a bare city name
  (the part before the first comma).
* Country-level (capital-city, approximate) coordinates are used **only**
  when the whole stored value is a country name, e.g. ``"Nigeria"``. A
  place like ``"Unknown Town, Nigeria"`` resolves to ``(None, None)`` —
  plotting an unknown town at its capital would be misleading.
* Anything unrecognized or ambiguous resolves to ``(None, None)``. Callers
  must keep such places visible as list entries, never plot them, and never
  substitute ``(0, 0)``.
"""

_CITIES = {
    # Nigeria
    "enugu": (6.4, 7.5),
    "lagos": (6.5, 3.4),
    "abuja": (9.1, 7.5),
    "kano": (12.0, 8.5),
    "ibadan": (7.4, 3.9),
    # Ghana / Guinea / Kenya / South Africa / Egypt
    "accra": (5.6, -0.2),
    "kumasi": (6.7, -1.6),
    "conakry": (9.5, -13.7),
    "nairobi": (-1.3, 36.8),
    "mombasa": (-4.1, 39.7),
    "johannesburg": (-26.2, 28.0),
    "cape town": (-33.9, 18.4),
    "cairo": (30.0, 31.2),
    # Canada
    "toronto": (43.7, -79.4),
    "vancouver": (49.3, -123.1),
    "montreal": (45.5, -73.6),
    "ottawa": (45.4, -75.7),
    "quebec city": (46.8, -71.2),
    "quebec": (46.8, -71.2),
    "calgary": (51.0, -114.1),
    # USA
    "new york": (40.7, -74.0),
    "los angeles": (34.1, -118.2),
    "chicago": (41.9, -87.6),
    "houston": (29.8, -95.4),
    "washington": (38.9, -77.0),
    "washington dc": (38.9, -77.0),
    "atlanta": (33.7, -84.4),
    # Latin America / Caribbean
    "mexico city": (19.4, -99.1),
    "havana": (23.1, -82.4),
    "lima": (-12.0, -77.0),
    "buenos aires": (-34.6, -58.4),
    "sao paulo": (-23.6, -46.6),
    "são paulo": (-23.6, -46.6),
    "brasilia": (-15.8, -47.9),
    "bogota": (4.7, -74.1),
    "bogotá": (4.7, -74.1),
    # Europe
    "london": (51.5, -0.1),
    "dublin": (53.3, -6.3),
    "paris": (48.9, 2.4),
    "berlin": (52.5, 13.4),
    "madrid": (40.4, -3.7),
    "rome": (41.9, 12.5),
    "moscow": (55.8, 37.6),
    "lisbon": (38.7, -9.1),
    "amsterdam": (52.4, 4.9),
    # Asia
    "guangzhou": (23.1, 113.3),
    "beijing": (39.9, 116.4),
    "shanghai": (31.2, 121.5),
    "seoul": (37.6, 127.0),
    "tokyo": (35.7, 139.7),
    "osaka": (34.7, 135.5),
    "hanoi": (21.0, 105.8),
    "ho chi minh city": (10.8, 106.7),
    "new delhi": (28.6, 77.2),
    "delhi": (28.6, 77.2),
    "mumbai": (19.1, 72.9),
    "kolkata": (22.6, 88.4),
    "manila": (14.6, 121.0),
    "jakarta": (-6.2, 106.8),
    # Oceania / Middle East
    "sydney": (-33.9, 151.2),
    "melbourne": (-37.8, 145.0),
    "canberra": (-35.3, 149.1),
    "auckland": (-36.8, 174.8),
    "dubai": (25.3, 55.3),
    "tel aviv": (32.1, 34.8),
}

# Country name -> capital (approximate, representative only). Used only when
# the whole place string is a country name.
_COUNTRIES = {
    "nigeria": (9.1, 7.5),
    "ghana": (5.6, -0.2),
    "guinea": (9.5, -13.7),
    "kenya": (-1.3, 36.8),
    "south africa": (-25.7, 28.2),
    "egypt": (30.0, 31.2),
    "canada": (45.4, -75.7),
    "united states": (38.9, -77.0),
    "usa": (38.9, -77.0),
    "mexico": (19.4, -99.1),
    "cuba": (23.1, -82.4),
    "peru": (-12.0, -77.0),
    "argentina": (-34.6, -58.4),
    "brazil": (-15.8, -47.9),
    "colombia": (4.7, -74.1),
    "united kingdom": (51.5, -0.1),
    "uk": (51.5, -0.1),
    "england": (51.5, -0.1),
    "scotland": (55.9, -3.2),
    "wales": (51.5, -3.2),
    "ireland": (53.3, -6.3),
    "france": (48.9, 2.4),
    "germany": (52.5, 13.4),
    "spain": (40.4, -3.7),
    "italy": (41.9, 12.5),
    "russia": (55.8, 37.6),
    "portugal": (38.7, -9.1),
    "netherlands": (52.4, 4.9),
    "china": (39.9, 116.4),
    "japan": (35.7, 139.7),
    "south korea": (37.6, 127.0),
    "korea": (37.6, 127.0),
    "india": (28.6, 77.2),
    "vietnam": (21.0, 105.8),
    "philippines": (14.6, 121.0),
    "australia": (-35.3, 149.1),
    "new zealand": (-41.3, 174.8),
}

# Pre-normalized "city, country" pairs for exact full-string matches.
_CITY_COUNTRY = {
    "enugu, nigeria": (6.4, 7.5),
    "lagos, nigeria": (6.5, 3.4),
    "abuja, nigeria": (9.1, 7.5),
    "accra, ghana": (5.6, -0.2),
    "toronto, canada": (43.7, -79.4),
    "vancouver, canada": (49.3, -123.1),
    "montreal, canada": (45.5, -73.6),
    "guangzhou, china": (23.1, 113.3),
    "new york, usa": (40.7, -74.0),
    "new york, united states": (40.7, -74.0),
    "london, uk": (51.5, -0.1),
    "london, united kingdom": (51.5, -0.1),
    "dublin, ireland": (53.3, -6.3),
    "nairobi, kenya": (-1.3, 36.8),
}


def _normalize(text):
    """Lowercase, trim, and collapse internal whitespace."""
    return " ".join((text or "").strip().lower().split())


def _valid(coords):
    """Reject anything outside real latitude/longitude ranges."""
    if coords is None:
        return False
    lat, lng = coords
    return (
        isinstance(lat, (int, float))
        and isinstance(lng, (int, float))
        and -90 <= lat <= 90
        and -180 <= lng <= 180
    )


def resolve_place(place):
    """Resolve a free-text place to ``(lat, lng)`` or ``(None, None)``.

    Never raises on odd input and never returns ``(0, 0)`` as a fallback.
    """
    key = _normalize(place)
    if not key:
        return (None, None)

    if key in _CITY_COUNTRY:
        coords = _CITY_COUNTRY[key]
    elif key.split(",")[0].strip() in _CITIES:
        coords = _CITIES[key.split(",")[0].strip()]
    elif "," not in key and key in _COUNTRIES:
        coords = _COUNTRIES[key]
    else:
        return (None, None)

    if not _valid(coords):
        return (None, None)
    return (float(coords[0]), float(coords[1]))
