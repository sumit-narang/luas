## About

The Luas is Dublin's tram network, operated by Transdev on behalf of the Transport Infrastructure Ireland. It has two lines — the **Red Line** (Saggart/Tallaght to The Point) and the **Green Line** (Bride's Glen to Broombridge) — with 67 stops across the city.

Unlike buses and trains, real-time Luas movement data is not available in any public GTFS feed. The NTA (National Transport Authority) publishes GTFS-RT for buses and Irish Rail, but Luas is excluded. The only source of Luas real-time data is the [Luas Forecasting API](http://luasforecasts.rpa.ie) — a stop-based API that tells you how many minutes until the next tram arrives at a given stop.

This project builds on that API to create something that doesn't exist publicly: a **historical record of Luas tram movements**. By polling every stop every 20 seconds and recording the arrival predictions, we can reconstruct where trams were at any point in time and replay an entire hour of tram activity on a map.

The system has been running continuously since early 2026, collecting data around the clock with no manual intervention.

---

## What it does

Every 20 seconds, a collector script polls the Luas Forecasting API for all 67 stops and records every tram arrival prediction into a PostgreSQL database. A web frontend lets you pick any date and hour, then watch the trams move across a map in real time.

---

## File Overview

| File | What it does |
|---|---|
| `collector.py` | Runs 24/7 on the server. Polls the Luas API every 20 seconds and saves tram arrival data to the database. |
| `api.py` | Web API (FastAPI) that the frontend talks to. Serves stop locations, available dates, and replay data. |
| `index.html` | The entire frontend — a Mapbox map with play/pause controls to replay tram movements. |
| `backup.sh` | Runs nightly via cron. Dumps the database, compresses it, uploads to Google Drive, and deletes local copies older than 7 days. |
| `luas-api.service` | Systemd config that keeps `api.py` running as a background service on the server. |
| `requirements.txt` | Python dependencies. Install with `pip install -r requirements.txt`. |
| `.env.example` | Template showing what environment variables are needed. Copy to `.env` and fill in your values. |

---

## Setup

### Requirements

- Python 3.11+
- PostgreSQL 16 with PostGIS
- A Mapbox account (for the map)

### Environment variables

Copy `.env.example` to `.env` and fill in:

```
DB_CONN=host=localhost dbname=luas_db user=luas password=YOUR_DB_PASSWORD
DB_URL=postgresql://luas:YOUR_DB_PASSWORD@localhost/luas_db
GMAIL_USER=you@gmail.com
GMAIL_PASS=your_gmail_app_password
TO_EMAIL=you@gmail.com
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Seed stops (one-time)

Before running the collector, populate the stops table with all 67 Luas stop names and GPS coordinates:

```bash
python seed_stops.py
```

> `seed_stops.py` is not in the repo — see `docs/instructions.md` for the original script.

### Run the collector

```bash
python collector.py
```

### Run the API

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

---

## Data source

Tram arrival predictions are fetched from the [Luas Forecasting API](http://luasforecasts.rpa.ie) operated by the Railway Procurement Agency (RPA). The NTA GTFS-RT feed does not include Luas data.

---

## Server

Hosted on a Hetzner CX23 VPS (2 vCPU, 4 GB RAM, 40 GB SSD) running Ubuntu 24.04. Nginx proxies the frontend and API through `sumitnarang.com`.
