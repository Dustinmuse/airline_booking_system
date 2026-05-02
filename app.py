from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from dotenv import load_dotenv
import os
import time
import threading
from datetime import datetime
import requests
from flask_sqlalchemy import SQLAlchemy
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

db = SQLAlchemy(app)

# (connect_timeout, read_timeout) — kept well under gunicorn's worker timeout so a
# single attempt cannot starve the worker even if OpenSky is unreachable.
OPEN_SKY_REQUEST_TIMEOUT = (3, 7)


def build_opensky_url():
    """Build the OpenSky URL for the most recent hour. Computed per-call so the
    time window doesn't go stale in long-running workers."""
    end = int(time.time())
    begin = end - 3600
    return f"https://opensky-network.org/api/states/all?begin={begin}&end={end}"


def opensky_seed_skipped():
    return os.getenv('SKIP_OPENSKY_SEED', '').strip().lower() in ('1', 'true', 'yes')


def fetch_opensky_states(max_attempts=2):
    """Fetch raw OpenSky state vectors. Returns the list under data['states'] on
    success, or None on any failure (network, non-200, JSON decode). Never raises."""
    url = build_opensky_url()
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, timeout=OPEN_SKY_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            app.logger.warning(
                'OpenSky request attempt %d/%d failed: %s',
                attempt, max_attempts, exc,
            )
            continue

        if response.status_code != 200:
            app.logger.warning(
                'OpenSky request attempt %d/%d returned HTTP %d',
                attempt, max_attempts, response.status_code,
            )
            continue

        try:
            data = response.json()
        except ValueError as exc:
            app.logger.warning('OpenSky response was not valid JSON: %s', exc)
            return None

        return data.get('states') or []

    return None

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
    airport_code = db.Column(db.String(10), unique=True)

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

# Home route
@app.route('/')
def home():
    return render_template('index.html')

# User registration route (new user)
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

# View booking route (for existing users)
@app.route('/booking/<int:passenger_id>')
def view_booking(passenger_id):
    bookings = db.session.query(Booking, Flight).join(Flight, Booking.flight_id == Flight.flight_id).filter(Booking.passenger_id == passenger_id).all()
    return render_template('view_booking.html', bookings=bookings, passenger_id=passenger_id)

# Booking a flight route
@app.route('/book', methods=['POST'])
def book_flight():
    passenger_id = session.get('passenger_id')
    if not passenger_id:
        return "Error: User not logged in.", 401
    flight_id = request.form['flight_id']
    seat_number = request.form['seat_number']

    # Check if seat is already taken
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
    """Render flights from the local database. The OpenSky network call lives in
    a background seeder, never on the request path, so this endpoint always
    responds quickly and never returns 5xx because of upstream issues."""
    DepartureAirport = aliased(Airport)
    ArrivalAirport = aliased(Airport)

    rows = (
        db.session.query(Flight, DepartureAirport, ArrivalAirport)
        .outerjoin(DepartureAirport, Flight.departure_airport == DepartureAirport.airport_id)
        .outerjoin(ArrivalAirport, Flight.arrival_airport == ArrivalAirport.airport_id)
        .order_by(Flight.departure_time.desc().nullslast())
        .limit(100)
        .all()
    )

    flights = [
        {
            'flight_id': flight.flight_id,
            'flight_number': flight.flight_number,
            'departure_airport': dep.airport_code if dep else 'UNKNOWN',
            'arrival_airport': arr.airport_code if arr else 'UNKNOWN',
            'departure_time': flight.departure_time,
            'arrival_time': flight.arrival_time,
        }
        for flight, dep, arr in rows
    ]

    return render_template('available_flights.html', flights=flights)


def insert_flights_from_api(flights_data):
    """Insert airports + flights from a list of normalized flight dicts.
    Returns the number of new Flight rows inserted."""
    airport_codes = set()
    for flight in flights_data:
        airport_codes.add(flight.get("departure_airport", "UNKNOWN")[:10])
        airport_codes.add(flight.get("arrival_airport", "UNKNOWN")[:10])

    for code in airport_codes:
        if not Airport.query.filter_by(airport_code=code).first():
            db.session.add(Airport(airport_code=code))
    db.session.commit()

    airports = Airport.query.all()
    airport_id_map = {a.airport_code: a.airport_id for a in airports}

    inserted = 0
    for flight in flights_data:
        dep_code = flight["departure_airport"][:10]
        arr_code = flight["arrival_airport"][:10]
        dep_id = airport_id_map.get(dep_code)
        arr_id = airport_id_map.get(arr_code)
        if dep_id and arr_id:
            exists = Flight.query.filter_by(
                flight_number=flight["flight_number"],
                departure_airport=dep_id,
                arrival_airport=arr_id,
                departure_time=flight["departure_time"],
                arrival_time=flight["arrival_time"]
            ).first()
            if not exists:
                db.session.add(Flight(
                    flight_number=flight["flight_number"],
                    departure_airport=dep_id,
                    arrival_airport=arr_id,
                    departure_time=flight["departure_time"],
                    arrival_time=flight["arrival_time"]
                ))
                inserted += 1
    db.session.commit()
    return inserted


def get_flights_data():
    """Fetch + normalize OpenSky flight states. Returns [] on any failure."""
    states = fetch_opensky_states()
    if not states:
        return []

    flights = []
    for flight in states:
        callsign = flight[1].strip() if flight[1] else "UNKNOWN"

        # OpenSky doesn't expose origin/destination airports in /states/all, so
        # the callsign is the best identifier we have for both ends.
        departure_airport = callsign
        arrival_airport = callsign

        first_seen = flight[4]  # last_contact
        last_seen = flight[3]   # time_position

        departure_time = datetime.fromtimestamp(first_seen) if first_seen else None
        arrival_time = datetime.fromtimestamp(last_seen) if last_seen else None

        flights.append({
            "flight_number": callsign,
            "departure_airport": departure_airport,
            "arrival_airport": arrival_airport,
            "departure_time": departure_time,
            "arrival_time": arrival_time,
        })

    return flights


def seed_flights_from_opensky():
    """Run the OpenSky → DB pipeline once. Returns inserted count, or -1 on
    failure. Safe to call from a background thread or an HTTP handler."""
    try:
        flights_data = get_flights_data()
        if not flights_data:
            app.logger.warning('OpenSky seed: no flight data from API')
            return 0
        return insert_flights_from_api(flights_data)
    except Exception as exc:
        app.logger.warning('OpenSky seed failed: %s', exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        return -1


def _background_seed():
    """Wrapper that establishes the Flask app context for the daemon thread."""
    with app.app_context():
        inserted = seed_flights_from_opensky()
        if inserted >= 0:
            app.logger.info('OpenSky background seed: inserted %d flights', inserted)


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


@app.route('/admin/refresh_flights', methods=['POST'])
def admin_refresh_flights():
    """Manually trigger an OpenSky seed. Guarded by the ADMIN_TOKEN env var
    matched against the X-Admin-Token request header."""
    expected_token = os.getenv('ADMIN_TOKEN')
    if not expected_token:
        return jsonify({'ok': False, 'error': 'ADMIN_TOKEN not configured'}), 503

    provided = request.headers.get('X-Admin-Token', '')
    if provided != expected_token:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    inserted = seed_flights_from_opensky()
    if inserted < 0:
        return jsonify({'ok': False, 'inserted': 0}), 502
    return jsonify({'ok': True, 'inserted': inserted})


with app.app_context():
    db.create_all()

if opensky_seed_skipped():
    app.logger.info('OpenSky startup seed skipped (SKIP_OPENSKY_SEED)')
else:
    # Run the initial seed in a daemon thread so a slow or unreachable OpenSky
    # endpoint can never block worker boot or the first request.
    threading.Thread(target=_background_seed, daemon=True, name='opensky-seed').start()

if __name__ == "__main__":
    app.run()
