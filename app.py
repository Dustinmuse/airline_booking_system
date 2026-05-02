from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from dotenv import load_dotenv
import csv
import io
import os
import random
import threading
from datetime import datetime, timedelta
import requests
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.orm import aliased

load_dotenv()


def normalized_database_url():
    url = os.getenv('DATABASE_URL')
    if url and url.startswith('postgres://'):
        return 'postgresql://' + url[len('postgres://') :]
    return url


app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

app.config['SQLALCHEMY_DATABASE_URI'] = normalized_database_url()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Neon (and most serverless Postgres providers) silently closes idle
# connections, which leaves stale entries in SQLAlchemy's pool and causes
# the first request after an idle gap to 500. pool_pre_ping issues a cheap
# SELECT 1 on checkout so dead connections are transparently replaced, and
# pool_recycle proactively rotates connections before Neon's idle timeout.
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 280,
}

db = SQLAlchemy(app)

# OurAirports publishes a daily-refreshed CSV of every airport in the world.
# Schema: https://ourairports.com/help/data-dictionary.html
OURAIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

# (connect_timeout, read_timeout) — kept under gunicorn's worker timeout so a
# single attempt can't starve the worker even if the host is unreachable.
OURAIRPORTS_REQUEST_TIMEOUT = (5, 30)

# Airport types we care about for a passenger booking system. Heliports,
# seaplane bases, closed airports, and small GA fields are skipped.
ELIGIBLE_AIRPORT_TYPES = {'large_airport', 'medium_airport'}

# ISO 3166-1 alpha-2 country code to filter airports to. Set to None to
# include airports from every country in the OurAirports dataset.
AIRPORT_COUNTRY_FILTER = 'US'

# Airline IATA codes used to build plausible-looking flight numbers for the
# synthetic schedule. These are real US carriers but the schedule itself is fake.
AIRLINE_CODES = [
    'AA',  # American
    'UA',  # United
    'DL',  # Delta
    'WN',  # Southwest
    'AS',  # Alaska
    'B6',  # JetBlue
    'F9',  # Frontier
    'NK',  # Spirit
    'G4',  # Allegiant
    'HA',  # Hawaiian
    'SY',  # Sun Country
]

# Cap on how many flights the synthetic generator will create per run, and the
# threshold below which a default seed will (re)generate flights.
SYNTHETIC_FLIGHT_TARGET = 200
SYNTHETIC_FLIGHT_MIN_THRESHOLD = 50


def data_seed_skipped():
    return os.getenv('SKIP_DATA_SEED', '').strip().lower() in ('1', 'true', 'yes')


# --- SQLAlchemy Models ---
class Passenger(db.Model):
    __tablename__ = 'passengers'
    passenger_id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    email = db.Column(db.String(100))
    phone_number = db.Column(db.String(20))
    date_of_birth = db.Column(db.Date)


class Airport(db.Model):
    __tablename__ = 'airports'
    airport_id = db.Column(db.Integer, primary_key=True)
    # Preferred IATA, falls back to ICAO when no IATA is published.
    airport_code = db.Column(db.String(10), unique=True)
    name = db.Column(db.String(200))
    city = db.Column(db.String(100))
    country = db.Column(db.String(10))
    iata_code = db.Column(db.String(10))
    icao_code = db.Column(db.String(10))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)


class Flight(db.Model):
    __tablename__ = 'flights'
    flight_id = db.Column(db.Integer, primary_key=True)
    flight_number = db.Column(db.String(20))
    departure_airport = db.Column(db.Integer, db.ForeignKey('airports.airport_id'))
    arrival_airport = db.Column(db.Integer, db.ForeignKey('airports.airport_id'))
    departure_time = db.Column(db.DateTime)
    arrival_time = db.Column(db.DateTime)


class Booking(db.Model):
    __tablename__ = 'bookings'
    booking_id = db.Column(db.Integer, primary_key=True)
    passenger_id = db.Column(db.Integer, db.ForeignKey('passengers.passenger_id'))
    flight_id = db.Column(db.Integer, db.ForeignKey('flights.flight_id'))
    seat_number = db.Column(db.String(10))
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)


# --- Lightweight schema migration ---
# `db.create_all()` only creates missing tables — it never alters existing
# columns. This helper backfills the airport metadata columns on databases
# provisioned against an older schema, and removes degenerate flight rows
# where the same airport is stored as both endpoints (which would never be a
# valid bookable flight regardless of how it got into the table).
def ensure_schema_upgrades():
    additions = [
        ('airports', 'name', 'VARCHAR(200)'),
        ('airports', 'city', 'VARCHAR(100)'),
        ('airports', 'country', 'VARCHAR(10)'),
        ('airports', 'iata_code', 'VARCHAR(10)'),
        ('airports', 'icao_code', 'VARCHAR(10)'),
        ('airports', 'latitude', 'DOUBLE PRECISION'),
        ('airports', 'longitude', 'DOUBLE PRECISION'),
    ]
    with db.engine.connect() as conn:
        for table, column, ddl in additions:
            try:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
                conn.commit()
            except Exception:
                # Column already exists or dialect doesn't support — both fine.
                conn.rollback()

        try:
            conn.execute(
                text('DELETE FROM flights WHERE departure_airport = arrival_airport')
            )
            conn.commit()
        except Exception:
            conn.rollback()


# --- OurAirports ingestion ---
def fetch_ourairports_csv(max_attempts=2):
    """Download the airports CSV. Returns the body text on success, None on
    any failure. Never raises."""
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(
                OURAIRPORTS_CSV_URL, timeout=OURAIRPORTS_REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            app.logger.warning(
                'OurAirports fetch attempt %d/%d failed: %s',
                attempt, max_attempts, exc,
            )
            continue

        if response.status_code != 200:
            app.logger.warning(
                'OurAirports fetch attempt %d/%d returned HTTP %d',
                attempt, max_attempts, response.status_code,
            )
            continue

        return response.text

    return None


def parse_airports_csv(csv_text):
    """Yield normalized airport dicts from the OurAirports CSV body. Filters
    to commercial-relevant airports that publish either an IATA or ICAO code,
    optionally restricted to a single country via AIRPORT_COUNTRY_FILTER."""
    reader = csv.DictReader(io.StringIO(csv_text))
    parsed = []
    for row in reader:
        airport_type = (row.get('type') or '').strip()
        if airport_type not in ELIGIBLE_AIRPORT_TYPES:
            continue

        iso_country = (row.get('iso_country') or '').strip().upper()
        if AIRPORT_COUNTRY_FILTER and iso_country != AIRPORT_COUNTRY_FILTER:
            continue

        iata = (row.get('iata_code') or '').strip().upper()
        icao = (row.get('gps_code') or row.get('ident') or '').strip().upper()
        code = iata or icao
        if not code:
            continue

        try:
            lat = float(row['latitude_deg']) if row.get('latitude_deg') else None
        except ValueError:
            lat = None
        try:
            lon = float(row['longitude_deg']) if row.get('longitude_deg') else None
        except ValueError:
            lon = None

        parsed.append({
            'airport_code': code[:10],
            'name': (row.get('name') or '').strip()[:200],
            'city': (row.get('municipality') or '').strip()[:100],
            'country': (row.get('iso_country') or '').strip()[:10],
            'iata_code': iata[:10] if iata else None,
            'icao_code': icao[:10] if icao else None,
            'latitude': lat,
            'longitude': lon,
        })
    return parsed


def upsert_airports(airports_data):
    """Insert new airports and update metadata for ones we already have. Returns
    (inserted, updated)."""
    existing = {a.airport_code: a for a in Airport.query.all()}
    inserted = 0
    updated = 0
    for data in airports_data:
        match = existing.get(data['airport_code'])
        if match is None:
            db.session.add(Airport(**data))
            inserted += 1
        else:
            match.name = data['name'] or match.name
            match.city = data['city'] or match.city
            match.country = data['country'] or match.country
            match.iata_code = data['iata_code'] or match.iata_code
            match.icao_code = data['icao_code'] or match.icao_code
            match.latitude = data['latitude'] if data['latitude'] is not None else match.latitude
            match.longitude = data['longitude'] if data['longitude'] is not None else match.longitude
            updated += 1
    db.session.commit()
    return inserted, updated


# --- Synthetic flight generation ---
def _great_circle_minutes(lat1, lon1, lat2, lon2):
    """Approximate flight time in minutes from straight-line great-circle
    distance plus 30 minutes of taxi/climb/descent overhead. Falls back to a
    random-ish duration when coordinates are missing."""
    if None in (lat1, lon1, lat2, lon2):
        return random.randint(90, 8 * 60)

    from math import radians, sin, cos, asin, sqrt

    r1, r2 = radians(lat1), radians(lat2)
    dlat = r2 - r1
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(r1) * cos(r2) * sin(dlon / 2) ** 2
    distance_km = 2 * 6371 * asin(sqrt(a))

    # Long-haul jet cruise ~ 850 km/h. Add 30 min for ground/climb/descent.
    return int(round(distance_km / 850 * 60)) + 30


def generate_synthetic_flights(count=SYNTHETIC_FLIGHT_TARGET):
    """Create `count` flights between random pairs of seeded airports, with
    departure times spread across the next 30 days. Returns inserted count."""
    airports = Airport.query.all()
    if len(airports) < 2:
        app.logger.warning('Synthetic flight gen skipped: < 2 airports seeded')
        return 0

    rng = random.Random()
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    inserted = 0
    attempts = 0
    max_attempts = count * 4

    while inserted < count and attempts < max_attempts:
        attempts += 1
        dep, arr = rng.sample(airports, 2)
        airline = rng.choice(AIRLINE_CODES)
        flight_number = f"{airline}{rng.randint(100, 9999)}"

        days_out = rng.randint(0, 30)
        hour = rng.randint(0, 23)
        minute = rng.choice((0, 5, 15, 30, 45))
        dep_time = now + timedelta(days=days_out, hours=hour, minutes=minute)

        duration = _great_circle_minutes(
            dep.latitude, dep.longitude, arr.latitude, arr.longitude
        )
        arr_time = dep_time + timedelta(minutes=duration)

        # (flight_number, departure_time) is treated as the natural key for
        # synthetic flights, which makes regeneration safely idempotent.
        existing = Flight.query.filter_by(
            flight_number=flight_number, departure_time=dep_time
        ).first()
        if existing:
            continue

        db.session.add(Flight(
            flight_number=flight_number,
            departure_airport=dep.airport_id,
            arrival_airport=arr.airport_id,
            departure_time=dep_time,
            arrival_time=arr_time,
        ))
        inserted += 1

    db.session.commit()
    return inserted


# --- Top-level seed pipeline ---
def seed_database(force_flights=False):
    """Seed airports from OurAirports and ensure we have a reasonable pool of
    synthetic flights. Returns a stats dict, or {'ok': False, 'error': ...} on
    a hard failure. Never raises."""
    try:
        csv_text = fetch_ourairports_csv()
        if csv_text is None:
            return {'ok': False, 'error': 'ourairports fetch failed'}

        airports_data = parse_airports_csv(csv_text)
        if not airports_data:
            return {'ok': False, 'error': 'no airports parsed'}

        inserted_airports, updated_airports = upsert_airports(airports_data)

        flight_count = Flight.query.count()
        inserted_flights = 0
        if force_flights or flight_count < SYNTHETIC_FLIGHT_MIN_THRESHOLD:
            inserted_flights = generate_synthetic_flights()

        return {
            'ok': True,
            'airports_inserted': inserted_airports,
            'airports_updated': updated_airports,
            'flights_inserted': inserted_flights,
            'flights_total': Flight.query.count(),
        }
    except Exception as exc:
        app.logger.warning('Seed pipeline failed: %s', exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        return {'ok': False, 'error': str(exc)}


def _background_seed():
    """Wrapper that establishes the Flask app context for the daemon thread."""
    with app.app_context():
        result = seed_database()
        if result.get('ok'):
            app.logger.info(
                'Background seed complete: %d airports inserted, %d updated, %d flights inserted',
                result['airports_inserted'],
                result['airports_updated'],
                result['flights_inserted'],
            )
        else:
            app.logger.warning('Background seed failed: %s', result.get('error'))


# --- Routes ---
@app.route('/')
def home():
    return render_template('index.html')


@app.route('/register', methods=['POST'])
def register():
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        phone_number = request.form['phone_number']
        date_of_birth = request.form['date_of_birth']

        passenger = Passenger(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone_number=phone_number,
            date_of_birth=date_of_birth
        )
        db.session.add(passenger)
        db.session.commit()
        return jsonify({"passenger_id": passenger.passenger_id})


@app.route('/booking/<int:passenger_id>')
def view_booking(passenger_id):
    bookings = (
        db.session.query(Booking, Flight)
        .join(Flight, Booking.flight_id == Flight.flight_id)
        .filter(Booking.passenger_id == passenger_id)
        .all()
    )
    return render_template('view_booking.html', bookings=bookings, passenger_id=passenger_id)


@app.route('/book', methods=['POST'])
def book_flight():
    passenger_id = session.get('passenger_id')
    if not passenger_id:
        return "Error: User not logged in.", 401
    flight_id = request.form['flight_id']
    seat_number = request.form['seat_number']

    existing = Booking.query.filter_by(flight_id=flight_id, seat_number=seat_number).first()
    if existing:
        return "Error: Seat is already taken!"

    booking = Booking(
        passenger_id=passenger_id,
        flight_id=flight_id,
        seat_number=seat_number,
        booking_date=datetime.utcnow()
    )
    db.session.add(booking)
    db.session.commit()
    return redirect(url_for('view_booking', passenger_id=passenger_id))


@app.route('/available_flights')
def available_flights():
    """Render flights from the local database. Data ingestion happens in a
    background seeder, never on the request path."""
    DepartureAirport = aliased(Airport)
    ArrivalAirport = aliased(Airport)

    rows = (
        db.session.query(Flight, DepartureAirport, ArrivalAirport)
        .outerjoin(DepartureAirport, Flight.departure_airport == DepartureAirport.airport_id)
        .outerjoin(ArrivalAirport, Flight.arrival_airport == ArrivalAirport.airport_id)
        .order_by(Flight.departure_time.asc().nullslast())
        .limit(100)
        .all()
    )

    flights = [
        {
            'flight_id': flight.flight_id,
            'flight_number': flight.flight_number,
            'departure_code': dep.airport_code if dep else 'UNKNOWN',
            'departure_name': dep.name if dep else None,
            'departure_city': dep.city if dep else None,
            'arrival_code': arr.airport_code if arr else 'UNKNOWN',
            'arrival_name': arr.name if arr else None,
            'arrival_city': arr.city if arr else None,
            'departure_time': flight.departure_time,
            'arrival_time': flight.arrival_time,
        }
        for flight, dep, arr in rows
    ]

    return render_template('available_flights.html', flights=flights)


@app.route('/signup')
def signup():
    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        passenger_id = request.form['passenger_id']
        exists = Passenger.query.filter_by(passenger_id=passenger_id).count()
        if exists > 0:
            session['passenger_id'] = passenger_id
            return render_template('main_menu.html', passenger_id=passenger_id)
    return render_template('login.html')


@app.route('/booking_form')
def booking_form():
    return render_template('booking_form.html')


@app.route('/main_menu')
def main_menu():
    passenger_id = session.get('passenger_id')
    if not passenger_id:
        return render_template('index.html')
    return render_template('main_menu.html', passenger_id=passenger_id)


@app.route('/admin/refresh_data', methods=['POST'])
def admin_refresh_data():
    """Re-run the OurAirports + synthetic-flight seed. Guarded by ADMIN_TOKEN
    matched against the X-Admin-Token request header. Pass ?force_flights=1 to
    regenerate the synthetic schedule even when one already exists."""
    expected_token = os.getenv('ADMIN_TOKEN')
    if not expected_token:
        return jsonify({'ok': False, 'error': 'ADMIN_TOKEN not configured'}), 503

    provided = request.headers.get('X-Admin-Token', '')
    if provided != expected_token:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    force_flights = request.args.get('force_flights', '').strip().lower() in ('1', 'true', 'yes')
    result = seed_database(force_flights=force_flights)
    status = 200 if result.get('ok') else 502
    return jsonify(result), status


with app.app_context():
    db.create_all()
    ensure_schema_upgrades()

if data_seed_skipped():
    app.logger.info('Startup data seed skipped (SKIP_DATA_SEED)')
else:
    # Run the initial seed in a daemon thread so a slow data fetch can never
    # block worker boot or the first request.
    threading.Thread(target=_background_seed, daemon=True, name='ourairports-seed').start()

if __name__ == "__main__":
    app.run()
