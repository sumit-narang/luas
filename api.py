from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from collections import OrderedDict
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv

load_dotenv()

# Per-date cache for the heavy replay-day query. Past days are immutable, so once
# computed they never change → instant on every revisit. Today is never cached
# (still accumulating). LRU-capped to bound memory.
DUBLIN = ZoneInfo("Europe/Dublin")
_replay_cache = OrderedDict()
_REPLAY_CACHE_MAX = 20

app = FastAPI()

# Compress JSON responses (~10x for the big replay-day payload). Clients send
# Accept-Encoding: gzip automatically; the dev proxy forwards it too.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_CONN = os.environ["DB_CONN"]


def get_db():
    return psycopg2.connect(DB_CONN, cursor_factory=psycopg2.extras.RealDictCursor)


@app.get("/api/stops")
def get_stops():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT stop_abv, stop_name, line, latitude, longitude FROM stops ORDER BY line, stop_abv")
    stops = cur.fetchall()
    cur.close()
    conn.close()
    return list(stops)


@app.get("/api/replay")
def get_replay(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    hour: int = Query(..., description="Hour 0-23"),
):
    # Fetch all observations for a given hour on a given date
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            ta.observed_at,
            ta.stop_abv,
            ta.direction,
            ta.destination,
            ta.due_mins,
            s.latitude,
            s.longitude,
            s.line
        FROM tram_arrivals ta
        JOIN stops s ON ta.stop_abv = s.stop_abv
        WHERE ta.observed_at >= %s::timestamptz
          AND ta.observed_at <  %s::timestamptz + INTERVAL '1 hour'
        ORDER BY ta.observed_at
    """, (f"{date}T{hour:02d}:00:00+00:00", f"{date}T{hour:02d}:00:00+00:00"))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/replay-day")
def get_replay_day(date: str = Query(..., description="Date in YYYY-MM-DD format")):
    """Return one observation per 30-second bucket per unique tram for a full day in Dublin local time.

    Only the fields the client actually uses are returned — stop coordinates and
    line are looked up client-side from /api/stops via stop_abv, so we don't ship
    latitude/longitude/line per row (no stops JOIN needed → smaller + faster).

    Past days are immutable, so their result is cached in-process (instant revisit);
    today is always recomputed since it's still accumulating data.
    """
    today = datetime.now(DUBLIN).date().isoformat()
    cacheable = date < today
    if cacheable and date in _replay_cache:
        _replay_cache.move_to_end(date)          # mark recently used
        return _replay_cache[date]

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (
            FLOOR(EXTRACT(EPOCH FROM ta.observed_at) / 30),
            ta.destination,
            ta.direction
        )
            TO_TIMESTAMP(FLOOR(EXTRACT(EPOCH FROM ta.observed_at) / 30) * 30) AS observed_at,
            ta.stop_abv,
            ta.direction,
            ta.destination,
            ta.due_mins
        FROM tram_arrivals ta
        WHERE ta.observed_at >= (%s::date::timestamp AT TIME ZONE 'Europe/Dublin')
          AND ta.observed_at <  ((%s::date + 1)::timestamp AT TIME ZONE 'Europe/Dublin')
        ORDER BY
            FLOOR(EXTRACT(EPOCH FROM ta.observed_at) / 30),
            ta.destination,
            ta.direction,
            ta.due_mins ASC
    """, (date, date))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = [dict(r) for r in rows]

    if cacheable:
        _replay_cache[date] = result
        _replay_cache.move_to_end(date)
        while len(_replay_cache) > _REPLAY_CACHE_MAX:
            _replay_cache.popitem(last=False)    # evict least-recently-used
    return result


@app.get("/api/dates")
def get_dates():
    # The collector runs 24/7, so data is continuous from the first day to the last.
    # Instead of scanning all ~30M rows for DISTINCT dates (a ~15s seq scan), we just
    # read the min/max observed_at (instant via the index) and fill in every day
    # between them. Same result, ~4ms instead of ~15s.
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT to_char(d, 'YYYY-MM-DD') AS date
        FROM generate_series(
            (SELECT (min(observed_at) AT TIME ZONE 'Europe/Dublin')::date FROM tram_arrivals),
            (SELECT (max(observed_at) AT TIME ZONE 'Europe/Dublin')::date FROM tram_arrivals),
            interval '1 day'
        ) d
        ORDER BY d DESC
    """)
    dates = [r["date"] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return dates


@app.get("/api/tram-positions")
def get_tram_positions(
    date: str = Query(...),
    timestamp: str = Query(..., description="ISO timestamp"),
):
    """
    For a given timestamp, return estimated position of each tram.
    A tram is identified by (destination, direction) seen at a stop.
    Its position is calculated by subtracting due_mins from the observation time
    to estimate when it departed the previous stop.
    """
    conn = get_db()
    cur = conn.cursor()

    # Get observations within 30 seconds of the requested timestamp
    cur.execute("""
        SELECT
            ta.observed_at,
            ta.stop_abv,
            ta.direction,
            ta.destination,
            ta.due_mins,
            s.latitude  AS stop_lat,
            s.longitude AS stop_lon,
            s.line
        FROM tram_arrivals ta
        JOIN stops s ON ta.stop_abv = s.stop_abv
        WHERE ta.observed_at BETWEEN %s::timestamptz - INTERVAL '30 seconds'
                                 AND %s::timestamptz + INTERVAL '30 seconds'
    """, (timestamp, timestamp))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    trams = []
    for r in rows:
        # Estimated arrival time at this stop
        arrival_time = r["observed_at"].timestamp() + (r["due_mins"] * 60)
        trams.append({
            "stop_abv":    r["stop_abv"],
            "direction":   r["direction"],
            "destination": r["destination"],
            "due_mins":    r["due_mins"],
            "stop_lat":    r["stop_lat"],
            "stop_lon":    r["stop_lon"],
            "line":        r["line"],
            "arrival_time": arrival_time,
        })

    return trams
