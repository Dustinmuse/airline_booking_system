# Fullstack Airline Booking System

A web-based airline booking system built with Flask (Python), MySQL, HTML/CSS/JS, and the OpenSky API for live flight data.

## Features

- User registration and login
- Book flights and select seats
- View available flights (live data from OpenSky)
- View current and past bookings
- Responsive and modern UI

## Requirements

- Python 3.8+
- MySQL server
- pip (Python package manager)

## Setup

1. **Clone the repository**  
   ```
   git clone <your-repo-url>
   cd fullstack_airline_booking_system
   ```

2. **Install dependencies**  
   ```
   pip install -r requirements.txt
   ```

3. **Configure environment variables**  
   - Copy `mysql.env.example` to `mysql.env` and fill in your MySQL credentials and secret key.

4. **Set up the database**  
   - Create the database and tables as required by the app (see your schema or migrations).

5. **Run the application**  
   ```
   python app.py
   ```
   The app will be available at `http://127.0.0.1:5000/`.

## Project Structure

- `app.py` - Main Flask application
- `templates/` - HTML templates (Jinja2)
- `static/css/` - Stylesheets
- `static/js/` - JavaScript files
- `requirements.txt` - Python dependencies

## Notes

- The app fetches live flight data from the [OpenSky Network API](https://opensky-network.org/).
- Make sure your MySQL server is running and accessible.
- For development, you may want to use a virtual environment.

