# Shelfie

Mobile app that turns a bookshelf photo into a structured personal library.

## Stack

| Layer | Choice |
|-------|--------|
| Frontend | React Native + Expo |
| Backend | Django + Django REST Framework |
| Local vision | YOLOv4-tiny (COCO book, OpenCV DNN, CPU) + OpenCV spine fallback |
| Vision-language | **Google Gemini** (hosted) — title/author from spines |
| Database | SQLite |

## Status

- [x] Project scaffold
- [x] Messy `catalog.csv` (125 books)
- [x] Django API skeleton + catalog load
- [x] Matching logic + tests
- [x] Local spine detection
- [x] Gemini OCR
- [x] Scan pipeline endpoint
- [x] Expo capture, upload, and results UI
- [ ] Review and library UI

## Backend setup

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # or: cp .env.example .env
python manage.py migrate
python manage.py load_catalog
python manage.py runserver
```

Health check: `GET http://127.0.0.1:8000/api/health/`

Scan a shelf photo:

```bash
curl -F "image=@photos/your-shelf.jpg" http://127.0.0.1:8000/api/scans/
```

Matching tests:

```bash
cd backend
pytest
```

## Frontend setup

```bash
cd frontend
npm install
npm start
```

For Expo Go on a physical phone, replace `localhost` in `frontend/.env` with
your computer's LAN IP (for example, `http://192.168.1.20:8000`) and start
Django with `python manage.py runserver 0.0.0.0:8000`.

## Architecture

Photo → Expo app → Django API → **local** YOLOv4-tiny / OpenCV spine detect → **hosted** Gemini OCR → catalog match → review → library.

Local does localization/crops (CPU, free, offline-capable). Gemini only sees cropped spines (cost/latency control).

## Latency & cost

To be measured once the scan pipeline works.