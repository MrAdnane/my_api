# Welcome to My Api
***

## Task
Build a backend API on a topic with 1000+ rows of data. It needs authentication, a token, CRUD, pagination (max 20 per page), a Redis cache, documentation, and cloud hosting.

## Description
An earthquakes API built with Python and FastAPI. Data is stored in SQLite. Login returns a JWT token. GET routes are public, while POST, PUT and DELETE require the token. Results are paginated (max 20 per page) and cached with Redis (in-memory fallback). Swagger docs are available at /docs.

## Installation
pip install -r requirements.txt
python seed.py
uvicorn app:app --reload

## Usage
- POST /auth/register and POST /auth/login (returns a token)
- GET /earthquakes?page=1&per_page=20
- GET /earthquakes/{id}
- POST, PUT, DELETE /earthquakes (header: Authorization: Bearer <token>)

Live URL: TODO
Postman documentation: TODO

### The Core Team
Adnane Mouloudi, Hazem Barman

<span><i>Made at <a href='https://qwasar.io'>Qwasar SV -- Software Engineering School</a></i></span>
<span><img alt='Qwasar SV -- Software Engineering School's Logo' src='https://storage.googleapis.com/qwasar-public/qwasar-logo_50x50.png' width='20px' /></span>