# Shelfie

Mobile app that turns a bookshelf photo into a structured personal library.

## Stack

| Layer | Choice |
|-------|--------|
| Frontend | React Native + Expo |
| Backend | Django + Django REST Framework |
| Local vision | TBD (pretrained, CPU) — spine detection |
| Vision-language | **Google Gemini** (hosted) — title/author from spines |
| Database | SQLite |

## Status

- [x] Project scaffold
- [x] Messy `catalog.csv` (125 books)
- [x] Django API skeleton + catalog load
- [x] Matching logic + tests
- [ ] Local spine detection
- [ ] Gemini OCR
- [ ] Scan pipeline endpoint
- [ ] Expo capture / review / library UI

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

## Architecture

Photo → Expo app → Django API → local spine detect → Gemini OCR → catalog match → review → library.

## Latency & cost

To be measured once the scan pipeline works.