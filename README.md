## About

The Luas is Dublin's tram network, operated by Transdev on behalf of the Transport Infrastructure Ireland. It has two lines — the **Red Line** (Saggart/Tallaght to The Point) and the **Green Line** (Bride's Glen to Broombridge) — with 67 stops across the city.

Unlike buses and trains, real-time Luas movement data is not available in any public GTFS feed. The NTA (National Transport Authority) publishes GTFS-RT for buses and Irish Rail, but Luas is excluded. The only source of Luas real-time data is the [Luas Forecasting API](http://luasforecasts.rpa.ie) — a stop-based API that tells you how many minutes until the next tram arrives at a given stop.

This project builds on that API to create something that doesn't exist publicly: a **historical record of Luas tram movements**. By polling every stop every 20 seconds and recording the arrival predictions, we can reconstruct where trams were at any point in time and replay an entire hour of tram activity on a map.

The system has been running continuously since early 2026, collecting data around the clock with no manual intervention.

---

## What it does

Every 20 seconds, a collector script polls the Luas Forecasting API for all 67 stops and records every tram arrival prediction into a PostgreSQL database. A web frontend (`web/index.html`) lets you pick any day and watch **3D tram models** replay the whole day's movements along the real track on a Mapbox map. Because the feed has no vehicle id, individual trams are reconstructed from the per-stop "DUE" moments (see `docs/replay-visualization.md`).

---

## Project structure

```
luas/
├── web/                     # frontend (served as the document root)
│   ├── index.html           # the 3D replay app
│   ├── assets/              # UI icons + map-style thumbnails (svg/png)
│   ├── data/                # route geometry (routes.geojson, routes-snapped.geojson)
│   └── three.min.js         # Three.js (local copy, git-ignored)
├── server/                  # backend (deployed to the VPS at /opt/luas)
│   ├── api.py               # FastAPI: stops, dates, replay/trips endpoints
│   ├── collector.py         # 24/7 poller → PostgreSQL
│   ├── backup.sh            # nightly DB dump → Google Drive (cron)
│   ├── luas-api.service     # systemd unit for api.py
│   └── requirements.txt     # Python dependencies
├── serve.py                 # local dev server: injects .env tokens, proxies /luas-api
├── docs/                    # design/perf notes (git-ignored)
├── .env / .env.example      # secrets (real .env is git-ignored)
└── README.md
```

> **Note:** the deployed VPS keeps a **flat** layout at `/opt/luas` (the `server/`
> files live directly there). The `server/` folder is just how the repo is
> organised — deploy by copying `server/api.py` → `/opt/luas/api.py`, etc.

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
python server/collector.py
```

### Run the API

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --app-dir server
```

### Run the frontend (local dev)

```bash
python serve.py     # serves web/ at http://localhost:8888 and proxies the API
```

---

## Data source

Tram arrival predictions are fetched from the [Luas Forecasting API](http://luasforecasts.rpa.ie) operated by the Railway Procurement Agency (RPA). The NTA GTFS-RT feed does not include Luas data.

---

## Server

Hosted on a Hetzner CX23 VPS (2 vCPU, 4 GB RAM, 40 GB SSD) running Ubuntu 24.04. Nginx proxies the frontend and API through `sumitnarang.com`.
