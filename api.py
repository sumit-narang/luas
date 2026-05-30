from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

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


@app.get("/api/dates")
def get_dates():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT DATE(observed_at AT TIME ZONE 'Europe/Dublin') as date
        FROM tram_arrivals
        ORDER BY date DESC
    """)
    dates = [r["date"].isoformat() for r in cur.fetchall()]
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
