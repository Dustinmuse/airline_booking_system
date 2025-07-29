// Booking form validation
const bookingForm = document.getElementById('booking-form');
if (bookingForm) {
    bookingForm.addEventListener('submit', function(event) {
        const seatNumber = document.getElementById('seat_number').value;
        const flightId = document.getElementById('flight_id').value;

        // Validate seat number format (e.g., A12 or B3)
        if (!seatNumber.match(/^[A-Z][0-9]{1,2}$/)) {
            alert('Please enter a valid seat number (e.g., A12)');
            event.preventDefault();
        }

        // Validate that flight ID is a positive number
        if (flightId <= 0 || isNaN(flightId)) {
            alert('Please enter a valid flight ID.');
            event.preventDefault();
        }
    });
}

// Filter flights by search query
function filterFlights() {
    const searchInput = document.getElementById('flight-search');
    const flightList = document.getElementById('flight-list');

    if (searchInput && flightList) {
        const filter = searchInput.value.toUpperCase();
        const flights = flightList.querySelectorAll('li');

        flights.forEach(function(flight) {
            const text = flight.textContent || flight.innerText;
            flight.style.display = text.toUpperCase().includes(filter) ? '' : 'none';
        });
    }
}

// Load available flights from Flask
function loadAvailableFlights() {
    const flightList = document.getElementById('flight-list');
    if (flightList) {
        fetch('/available_flights')
            .then(response => response.json())
            .then(data => {
                flightList.innerHTML = '';
                data.flights.forEach(flight => {
                    const li = document.createElement('li');
                    li.classList.add('flight');
                    li.textContent = `Flight ${flight.flight_number} - ${flight.departure_airport} to ${flight.arrival_airport}`;
                    flightList.appendChild(li);
                });
            })
            .catch(error => console.error('Error fetching flights:', error));
    }
}

// Load bookings list via AJAX (optional: implement this route in Flask)
function loadBookings() {
    const bookingsList = document.getElementById('bookings-list');
    if (bookingsList) {
        fetch('/api/bookings')
            .then(response => response.json())
            .then(data => {
                bookingsList.innerHTML = '';
                data.bookings.forEach(booking => {
                    const li = document.createElement('li');
                    li.textContent = `Booking ID: ${booking.id}, Flight: ${booking.flight_number}`;
                    bookingsList.appendChild(li);
                });
            })
            .catch(error => console.error('Error fetching bookings:', error));
    }
}

// Initialize when the DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    loadAvailableFlights();
    loadBookings();
});

async function handleSignup(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);

    try {
        const response = await fetch(form.action, {
            method: form.method,
            body: formData
        });

        if (response.ok) {
            const data = await response.json();
            console.log('Server response:', data); // Log the response for debugging
            if (data.passenger_id) {
                document.getElementById('passenger-id').textContent = data.passenger_id;
                document.getElementById('passenger-id-display').style.display = 'block';
                form.style.display = 'none'; // Hide the form after successful signup
                form.reset();
            } else {
                alert('Registration failed. Missing passenger ID in the response.');
            }
        } else {
            const errorText = await response.text(); // Log the error response text
            console.error('Error response:', errorText);
            alert('Registration failed. Please try again.');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('An error occurred. Please try again later.');
    }
}

function validatePassword(password) {
    const regex = /^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,}$/; // At least 8 characters, 1 letter, 1 number
    return regex.test(password);
}

document.querySelector('.signup-form').addEventListener('submit', function(event) {
    const password = document.getElementById('password').value;
    if (!validatePassword(password)) {
        alert('Password must be at least 8 characters long and include at least one letter and one number.');
        event.preventDefault();
    }
});