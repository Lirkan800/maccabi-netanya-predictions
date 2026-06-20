import json
import requests
from datetime import datetime, timedelta

SETTINGS_FILE = "data/settings.json"


def load_settings():
    with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


settings = load_settings()
api_key = settings["api_football_key"]

url = "https://v3.football.api-sports.io/leagues"

headers = {
    "x-apisports-key": api_key
}

today = datetime.now().date()
tomorrow = today + timedelta(days=1)

today = datetime.now().date()

params = {
    "date": "2026-08-22"
}

response = requests.get(url, headers=headers, params=params)

print("Status code:", response.status_code)

data = response.json()

print("Errors:", data.get("errors"))
print("Results:", data.get("results"))

fixtures = data.get("response", [])

print("Number of fixtures:", len(fixtures))

leagues = data.get("response", [])

for item in leagues:
    league = item["league"]
    country = item["country"]

    print("--------------------")
    print("League ID:", league["id"])
    print("League Name:", league["name"])
    print("Country:", country["name"])