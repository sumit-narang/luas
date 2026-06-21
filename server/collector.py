import requests
import xml.etree.ElementTree as ET
import psycopg2
import psycopg2.extras
import time
import logging
import logging.handlers
import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# Configuration
DB_CONN       = os.environ["DB_CONN"]
BUFFER_FILE   = "/var/luas/buffer.jsonl"
HEARTBEAT_FILE = "/var/luas/heartbeat"
LOG_FILE      = "/var/log/luas/collector.log"
POLL_INTERVAL = 20    # seconds between full cycles
API_DELAY     = 0.3   # seconds between individual stop API calls
API_TIMEOUT   = 10    # seconds before a single API call times out
MAX_BACKOFF   = 300   # max seconds to wait when DB keeps failing

# Logging — rotates daily, keeps 30 days
log = logging.getLogger("luas")
log.setLevel(logging.INFO)
handler = logging.handlers.TimedRotatingFileHandler(
    LOG_FILE, when="midnight", backupCount=30
)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(handler)
log.addHandler(logging.StreamHandler())


def connect_db():
    backoff = 10
    while True:
        try:
            conn = psycopg2.connect(DB_CONN)
            log.info("Database connected")
            return conn
        except Exception as e:
            log.error(f"DB connection failed: {e}. Retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)


def get_stops(conn):
    cur = conn.cursor()
    cur.execute("SELECT stop_abv, stop_name, line FROM stops ORDER BY line, stop_abv")
    stops = cur.fetchall()
    cur.close()
    return stops


def fetch_stop(stop_abv):
    for attempt in range(3):
        try:
            r = requests.get(
                "http://luasforecasts.rpa.ie/xml/get.ashx",
                params={"action": "forecast", "stop": stop_abv, "encrypt": "false"},
                timeout=API_TIMEOUT
            )
            if r.status_code == 200 and "<stopInfo" in r.text:
                return r.text
            log.warning(f"Bad response for {stop_abv}: status {r.status_code}")
        except Exception as e:
            log.warning(f"API error for {stop_abv} (attempt {attempt + 1}): {e}")
            if attempt < 2:
                time.sleep(5)
    return None


def parse_stop(xml_text, stop_abv, stop_name, line, observed_at):
    rows = []
    try:
        root = ET.fromstring(xml_text)
        for direction in root.findall("direction"):
            dir_name = direction.attrib.get("name", "")
            for tram in direction.findall("tram"):
                destination = tram.attrib.get("destination", "").strip()
                due_str = tram.attrib.get("dueMins", "").strip()

                if not destination or destination.lower() == "no trams":
                    continue

                # API returns "DUE" when tram is arriving now
                if due_str.upper() == "DUE":
                    due_mins = 0
                else:
                    try:
                        due_mins = int(due_str)
                    except ValueError:
                        continue

                rows.append({
                    "observed_at": observed_at.isoformat(),
                    "stop_abv":    stop_abv,
                    "stop_name":   stop_name,
                    "line":        line,
                    "direction":   dir_name,
                    "destination": destination,
                    "due_mins":    due_mins,
                })
    except Exception as e:
        log.error(f"Parse error for {stop_abv}: {e}")
    return rows


def insert_rows(conn, rows):
    if not rows:
        return 0
    cur = conn.cursor()
    psycopg2.extras.execute_values(cur, """
        INSERT INTO tram_arrivals
            (observed_at, stop_abv, stop_name, line, direction, destination, due_mins)
        VALUES %s
    """, [
        (r["observed_at"], r["stop_abv"], r["stop_name"],
         r["line"], r["direction"], r["destination"], r["due_mins"])
        for r in rows
    ])
    conn.commit()
    cur.close()
    return len(rows)


def write_buffer(rows):
    with open(BUFFER_FILE, "a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    log.info(f"Buffered {len(rows)} rows to file")


def flush_buffer(conn):
    if not os.path.exists(BUFFER_FILE):
        return
    rows = []
    with open(BUFFER_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if rows:
        inserted = insert_rows(conn, rows)
        log.info(f"Flushed {inserted} buffered rows from file")
    os.remove(BUFFER_FILE)


def write_heartbeat():
    with open(HEARTBEAT_FILE, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())


def run():
    log.info("=== Luas collector starting ===")
    conn = connect_db()
    stops = get_stops(conn)
    log.info(f"Loaded {len(stops)} stops")

    last_heartbeat = 0
    cycle = 0

    while True:
        cycle_start = time.time()
        cycle += 1
        all_rows = []

        # Flush any buffered rows from previous DB outage
        try:
            flush_buffer(conn)
        except Exception as e:
            log.error(f"Buffer flush failed: {e}")

        # Poll every stop
        for stop_abv, stop_name, line in stops:
            xml = fetch_stop(stop_abv)
            if xml:
                observed_at = datetime.now(timezone.utc)
                rows = parse_stop(xml, stop_abv, stop_name, line, observed_at)
                all_rows.extend(rows)
            time.sleep(API_DELAY)

        # Insert into DB — buffer to file if DB is down
        try:
            if conn.closed:
                conn = connect_db()
                stops = get_stops(conn)
            inserted = insert_rows(conn, all_rows)
            log.info(f"Cycle {cycle}: {inserted} rows inserted from {len(stops)} stops")
        except Exception as e:
            log.error(f"DB insert failed: {e}. Buffering {len(all_rows)} rows")
            write_buffer(all_rows)
            try:
                conn.close()
            except Exception:
                pass
            conn = connect_db()
            stops = get_stops(conn)

        # Write heartbeat every 5 minutes
        now = time.time()
        if now - last_heartbeat > 300:
            write_heartbeat()
            last_heartbeat = now

        # Sleep for remainder of poll interval
        elapsed = time.time() - cycle_start
        sleep_time = max(0, POLL_INTERVAL - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)


if __name__ == "__main__":
    run()
