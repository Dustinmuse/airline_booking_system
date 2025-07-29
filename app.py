from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from dotenv import load_dotenv
import os
import time
from datetime import datetime
import requests
from flask_sqlalchemy import SQLAlchemy

# Load environment variables from .env file (use locally only)
# load_dotenv(dotenv_path='c:\\CS418_Python\\fullstack_airline_booking_system\\mysql.env')

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

# Use the DATABASE_URL environment variable for PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

current_time = int(time.time())
start_time = current_time - 3600

OPEN_SKY_API_URL = f"https://opensky-network.org/api/states/all?begin={start_time}&end={current_time}"

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
    # Fetch flight data from OpenSky API
    response = requests.get(OPEN_SKY_API_URL)

    if response.status_code == 200:
        data = response.json()  # Parse the JSON data
        flights = data['states'][:100]  # Extract and limit to the first 100 flights

        return render_template('available_flights.html', flights=flights)  # Pass the flight data to the template
    else:
        return "Error: Unable to fetch flight data from OpenSky API", 500


def insert_flights_from_api(flights_data):
    # Insert airports first (to avoid FK constraint issues)
    airport_codes = set()
    for flight in flights_data:
        airport_codes.add(flight.get("departure_airport", "UNKNOWN")[:10])
        airport_codes.add(flight.get("arrival_airport", "UNKNOWN")[:10])

    # Insert airports if not exist
    for code in airport_codes:
        if not Airport.query.filter_by(airport_code=code).first():
            db.session.add(Airport(airport_code=code))
    db.session.commit()

    # Fetch airport IDs into a dict
    airports = Airport.query.all()
    airport_id_map = {a.airport_code: a.airport_id for a in airports}

    # Insert flights if not exist
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
    db.session.commit()
    print("Flights and airports inserted successfully!")


def get_flights_data():
    url = OPEN_SKY_API_URL
    response = requests.get(url)

    if response.status_code != 200:
        print("Failed to fetch flight data")
        return []

    data = response.json()
    flights = []
    states = data.get("states", [])

    for flight in states:
        callsign = flight[1].strip() if flight[1] else "UNKNOWN"

        # Use the raw callsign as the airport code
        departure_airport = callsign
        arrival_airport = callsign

        first_seen = flight[4]  # last_contact (best guess for departure)
        last_seen = flight[3]   # time_position (optional guess for arrival)

        departure_time = datetime.fromtimestamp(first_seen).strftime('%Y-%m-%d %H:%M:%S') if first_seen else None
        arrival_time = datetime.fromtimestamp(last_seen).strftime('%Y-%m-%d %H:%M:%S') if last_seen else None

        flight_info = {
            "flight_number": callsign,
            "departure_airport": departure_airport,
            "arrival_airport": arrival_airport,
            "departure_time": departure_time,
            "arrival_time": arrival_time
        }
        flights.append(flight_info)

    return flights


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


# Initialize database when app starts
with app.app_context():
    db.create_all()
    insert_flights_from_api(get_flights_data())

if __name__ == "__main__":
    app.run()
