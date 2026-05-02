# Airline Booking System

A web-based airline booking system featuring a Flask (Python) backend, PostgreSQL database, and a modern HTML/CSS/JavaScript frontend. Integrates live flight data using the OpenSky API.

## Key Features

- User registration and login (Flask backend)
- Book flights and select seats
- View available flights (live data from OpenSky, backend integration)
- View current and past bookings
- Responsive UI (HTML/CSS/JavaScript)
- RESTful API endpoints

## Tech Stack

- **Backend:** Python 3.8+, Flask
- **Frontend:** HTML, CSS, JavaScript (Jinja2 templates)
- **Database:** PostgreSQL
- **External API:** OpenSky Network API

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
     # Optional: set to 1/true/yes to skip the background OpenSky seed at boot
     SKIP_OPENSKY_SEED=
     # Optional: shared secret required by POST /admin/refresh_flights via the
     # X-Admin-Token header. Leave unset to disable the admin endpoint.
     ADMIN_TOKEN=
     ```

### Flight data and OpenSky

`/available_flights` reads exclusively from the local `flights` table — it never
calls OpenSky on the request path, so the page stays fast even if the OpenSky
API is unreachable (which is common from cloud-provider IP ranges).

The `flights` table is populated by:

- A best-effort daemon-thread seed that runs once at app boot. Failures are
  logged via `app.logger.warning` and never block startup.
- An admin endpoint to re-seed on demand:
  ```
  curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
       https://your-host/admin/refresh_flights
  ```
  Returns `{"ok": true, "inserted": N}` on success.

Set `SKIP_OPENSKY_SEED=1` to disable the boot-time seed entirely (useful for
local development or when OpenSky is known to be down).

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

*This project uses PostgreSQL for data storage. Make sure to update your `.env` with the correct `DATABASE_URL` and `SECRET_KEY`.*
