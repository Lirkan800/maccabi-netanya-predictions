import json
import requests

SETTINGS_FILE = "data/settings.json"

def load_settings():
    with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)

settings = load_settings()
api_key = settings["api_football_key"]

url = "https://v3.football.api-sports.io/fixtures"

headers = {
    "x-apisports-key": api_key
}

params = {
    "date": "2026-06-23"  # שנה לתאריך שאתה רוצה
}

response = requests.get(url, headers=headers, params=params)
data = response.json()

print("Status code:", response.status_code)
print("Errors:", data.get("errors"))
print("Results:", data.get("results"))

fixtures = data.get("response", [])

for item in fixtures:
    fixture = item["fixture"]
    teams = item["teams"]
    goals = item["goals"]
    league = item["league"]

    print("--------------------")
    print("Fixture ID:", fixture["id"])
    print("Date:", fixture["date"])
    print("Status:", fixture["status"]["short"])
    print("League:", league["name"])
    print("Match:", teams["home"]["name"], "-", teams["away"]["name"])
    print("Score:", goals["home"], "-", goals["away"])