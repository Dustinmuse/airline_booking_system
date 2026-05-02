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

// Initialize when the DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Endpoints removed because they don't return JSON
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

// Password validation removed as there is no password field.