# Airline Booking System

A web-based airline booking system featuring a Flask (Python) backend, PostgreSQL database, and a modern HTML/CSS/JavaScript frontend. Real-world airport data is sourced from the [OurAirports](https://github.com/davidmegginson/ourairports-data) open dataset, with a synthetic flight schedule generated on top of those airports.

## Key Features

- User registration and login (Flask backend)
- Book flights and select seats
- View available flights (real airports from OurAirports + synthetic schedule)
- View current and past bookings
- Responsive UI (HTML/CSS/JavaScript)
- RESTful API endpoints

## Tech Stack

- **Backend:** Python 3.8+, Flask
- **Frontend:** HTML, CSS, JavaScript (Jinja2 templates)
- **Database:** PostgreSQL
- **Airport data:** [OurAirports CSV](https://davidmegginson.github.io/ourairports-data/airports.csv)

## Project Structure

- `app.py` - Flask application entry point
- `templates/` - Jinja2 HTML templates
- `static/` - Static files (CSS, JS, images)
- `requirements.txt` - Python dependencies
- `.env.example` - Environment variable sample

## Setup Instructions

1. **Clone the repository**

   ```
   git clone https://github.com/yourusername/airline_booking_system.git
   cd airline_booking_system
   ```

2. **Install dependencies**

   ```
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   - Copy `.env.example` to `.env` and update with your info:
     ```
     DATABASE_URL=postgresql://username:password@localhost:5432/yourdbname
     SECRET_KEY=your_secret_key
     # Optional: set to 1/true/yes to skip the background data seed at boot
     SKIP_DATA_SEED=
     # Optional: shared secret required by POST /admin/refresh_data via the
     # X-Admin-Token header. Leave unset to disable the admin endpoint.
     ADMIN_TOKEN=
     ```

### Flight data

`/available_flights` reads exclusively from the local `flights` table — the
data fetch happens in a background seeder, never on the request path, so the
page stays fast and responsive.

The data is sourced from the [OurAirports](https://github.com/davidmegginson/ourairports-data)
open dataset, which publishes a daily-refreshed CSV of every airport in the
world (name, city, country, IATA/ICAO codes, lat/lon, type). On boot the app:

1. Downloads `https://davidmegginson.github.io/ourairports-data/airports.csv`.
2. Filters to large/medium airports that publish an IATA or ICAO code, and
   upserts them into the `airports` table.
3. If the `flights` table has fewer than 50 rows, generates a synthetic
   schedule of ~200 flights by pairing random airports with realistic flight
   numbers (real airline IATA prefixes), departure times spread over the next
   30 days, and durations approximated from the great-circle distance.

Note that OurAirports does not publish flight schedules — only airport data.
The schedule on top is intentionally synthetic so the booking flow has data
to work with.

The seed is best-effort: it runs in a daemon thread at app boot and any
failure is logged via `app.logger.warning` without blocking startup. To
re-seed on demand:

```
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
     https://your-host/admin/refresh_data
```

Append `?force_flights=1` to also regenerate the synthetic schedule even when
flights already exist. Returns `{"ok": true, ...}` on success.

Set `SKIP_DATA_SEED=1` to disable the boot-time seed entirely (useful for
local development or offline work).

4. **Set up the PostgreSQL database**
   - Make sure PostgreSQL is running and your database is created.

5. **Run the backend application**
   ```
   python app.py
   ```
   The app will be available at [http://127.0.0.1:5000/](http://127.0.0.1:5000/).

## Live Demo

🌐 **Website:** [https://airline-booking-system-klwk.onrender.com](https://airline-booking-system-klwk.onrender.com)

## API Endpoints

- `/api/flights` - List available flights
- `/api/book` - Book a flight
- `/api/login` - User authentication

## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

---

_This project uses PostgreSQL for data storage. Make sure to update your `.env` with the correct `DATABASE_URL` and `SECRET_KEY`._
