from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from functools import wraps
from datetime import datetime, timedelta
import os
import uuid
import json
import sqlite3
import requests
import pg8000.dbapi
from urllib.parse import urlparse, unquote

app = Flask(__name__)
app.config["SESSION_PERMANENT"] = False
app.secret_key = os.environ.get("SECRET_KEY", "temporary_secret_key_for_test")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Phxyuejhhoakh!")
AUTO_SYNC_TOKEN = os.environ.get("AUTO_SYNC_TOKEN", "change_me_auto_sync_token")
NETANYA_TEAM_ID = 4505
SETTINGS_FILE = "data/settings.json"
DATABASE_URL = os.environ.get("DATABASE_URL")
SQLITE_DB = os.environ.get("SQLITE_DB", "data/app.db")

teams = [
    "מכבי נתניה", "מכבי תל אביב", "מכבי חיפה", "הפועל באר שבע",
    "בית״ר ירושלים", "הפועל תל אביב", "הפועל חיפה", "הפועל ירושלים",
    "הפועל פתח תקווה", "מכבי פתח תקווה", "בני סכנין",
    "הפועל רמת גן", "עירוני טבריה", "עירוני קריית שמונה"
]

TEAM_LOGOS = {
    "מכבי נתניה": "מכבי נתניה.png",

    "בני סכנין": "בני סכנין.png",

    "ביתר ירושלים": "ביתר ירושלים.png",
    "בית״ר ירושלים": "ביתר ירושלים.png",
    "בית\"ר ירושלים": "ביתר ירושלים.png",
    "בית\"ר י-ם": "ביתר ירושלים.png",

    "מכבי חיפה": "מכבי חיפה.png",

    "מכבי תל אביב": "מכבי תל אביב.png",
    "מכבי ת\"א": "מכבי תל אביב.png",

    "הפועל באר שבע": "הפועל באר שבע.png",
    "הפועל ב\"ש": "הפועל באר שבע.png",

    "הפועל תל אביב": "הפועל תל אביב.png",
    "הפועל ת\"א": "הפועל תל אביב.png",

    "הפועל חיפה": "הפועל חיפה.png",
    "הפועל ירושלים": "הפועל ירושלים.png",

    "מכבי פתח תקווה": "מכבי פתח תקווה.png",
    "מכבי פ\"ת": "מכבי פתח תקווה.png",

    "הפועל פתח תקווה": "הפועל פתח תקווה.png",
    "הפועל פ\"ת": "הפועל פתח תקווה.png",

    "הפועל רמת גן": "הפועל רמת גן.png",
    "הפועל ר\"ג": "הפועל רמת גן.png",

    "עירוני קריית שמונה": "הפועל קריית שמונה.png",
    "הפועל קריית שמונה": "הפועל קריית שמונה.png",
    "הפועל ק\"ש": "הפועל קריית שמונה.png",

    "עירוני טבריה": "עירוני טבריה.png",
    "עירוני דורות טבריה": "עירוני טבריה.png"
}


def is_postgres():
    return bool(DATABASE_URL)


def get_db_connection():
    if is_postgres():
        url = urlparse(DATABASE_URL)

        return pg8000.dbapi.connect(
            user=unquote(url.username or ""),
            password=unquote(url.password or ""),
            host=url.hostname,
            port=url.port or 5432,
            database=(url.path or "").lstrip("/")
        )

    os.makedirs(os.path.dirname(SQLITE_DB), exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn

def db_execute(query, params=None, fetchone=False, fetchall=False):
    params = params or []

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(query, params)

        result = None

        if fetchone or fetchall:
            rows = cur.fetchall() if fetchall else [cur.fetchone()]
            columns = [desc[0] for desc in cur.description]

            dict_rows = []
            for row in rows:
                if row is not None:
                    dict_rows.append(dict(zip(columns, row)))

            if fetchone:
                result = dict_rows[0] if dict_rows else None
            else:
                result = dict_rows

        conn.commit()
        cur.close()
        return result

def normalize_row(row):
    if row is None:
        return None
    return dict(row)


def init_db():
    if is_postgres():
        queries = [
            """
            CREATE TABLE IF NOT EXISTS players (
                name TEXT PRIMARY KEY,
                password TEXT NOT NULL DEFAULT '',
                points INTEGER NOT NULL DEFAULT 0,
                streak INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                home_team_id INTEGER,
                away_team_id INTEGER,
                match_date TEXT NOT NULL,
                match_time TEXT NOT NULL DEFAULT '',
                is_playoff BOOLEAN NOT NULL DEFAULT FALSE,
                home_score INTEGER,
                away_score INTEGER,
                status TEXT NOT NULL DEFAULT 'scheduled',
                api_fixture_id INTEGER,
                source TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS predictions (
                id SERIAL PRIMARY KEY,
                match_id TEXT NOT NULL,
                player TEXT NOT NULL,
                guess_home INTEGER NOT NULL,
                guess_away INTEGER NOT NULL,
                points INTEGER NOT NULL DEFAULT 0,
                bonus INTEGER NOT NULL DEFAULT 0,
                exact BOOLEAN NOT NULL DEFAULT FALSE,
                match_finished BOOLEAN NOT NULL DEFAULT FALSE,
                UNIQUE(match_id, player)
            )
            """
        ]
    else:
        queries = [
            """
            CREATE TABLE IF NOT EXISTS players (
                name TEXT PRIMARY KEY,
                password TEXT NOT NULL DEFAULT '',
                points INTEGER NOT NULL DEFAULT 0,
                streak INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                home_team_id INTEGER,
                away_team_id INTEGER,
                match_date TEXT NOT NULL,
                match_time TEXT NOT NULL DEFAULT '',
                is_playoff INTEGER NOT NULL DEFAULT 0,
                home_score INTEGER,
                away_score INTEGER,
                status TEXT NOT NULL DEFAULT 'scheduled',
                api_fixture_id INTEGER,
                source TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                player TEXT NOT NULL,
                guess_home INTEGER NOT NULL,
                guess_away INTEGER NOT NULL,
                points INTEGER NOT NULL DEFAULT 0,
                bonus INTEGER NOT NULL DEFAULT 0,
                exact INTEGER NOT NULL DEFAULT 0,
                match_finished INTEGER NOT NULL DEFAULT 0,
                UNIQUE(match_id, player)
            )
            """
        ]

    for query in queries:
        db_execute(query)

    # Existing installations may have been created before team IDs were stored.
    # Add the columns safely without deleting or rebuilding any existing data.
    if is_postgres():
        db_execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS home_team_id INTEGER")
        db_execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS away_team_id INTEGER")
    else:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(matches)")
            existing_columns = {row[1] for row in cur.fetchall()}
            if "home_team_id" not in existing_columns:
                cur.execute("ALTER TABLE matches ADD COLUMN home_team_id INTEGER")
            if "away_team_id" not in existing_columns:
                cur.execute("ALTER TABLE matches ADD COLUMN away_team_id INTEGER")
            conn.commit()
            cur.close()


def load_players():
    rows = db_execute(
        "SELECT name, password, points, streak FROM players ORDER BY name",
        fetchall=True
    )

    data = {}
    for row in rows:
        row = normalize_row(row)
        data[row["name"]] = {
            "password": row.get("password") or "",
            "points": int(row.get("points") or 0),
            "streak": int(row.get("streak") or 0)
        }

    return data


def save_players():
    global players

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM players")

        if is_postgres():
            for name, data in players.items():
                cur.execute(
                    """
                    INSERT INTO players (name, password, points, streak)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        name,
                        data.get("password", ""),
                        int(data.get("points", 0)),
                        int(data.get("streak", 0))
                    )
                )
        else:
            for name, data in players.items():
                cur.execute(
                    """
                    INSERT INTO players (name, password, points, streak)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        name,
                        data.get("password", ""),
                        int(data.get("points", 0)),
                        int(data.get("streak", 0))
                    )
                )

        conn.commit()
        cur.close()


def load_matches():
    rows = db_execute(
        """
        SELECT id, home_team, away_team, home_team_id, away_team_id,
               match_date, match_time, is_playoff, home_score, away_score,
               status, api_fixture_id, source
        FROM matches
        ORDER BY match_date, match_time
        """,
        fetchall=True
    )

    matches = []
    for row in rows:
        row = normalize_row(row)
        matches.append({
            "id": row["id"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "home_team_id": row.get("home_team_id"),
            "away_team_id": row.get("away_team_id"),
            "match_date": row["match_date"],
            "match_time": row.get("match_time") or "",
            "is_playoff": bool(row.get("is_playoff")),
            "home_score": row.get("home_score"),
            "away_score": row.get("away_score"),
            "status": row.get("status") or "scheduled",
            "api_fixture_id": row.get("api_fixture_id"),
            "source": row.get("source")
        })

    return matches


def save_matches(matches):
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM matches")

        if is_postgres():
            insert_query = """
                INSERT INTO matches
                (id, home_team, away_team, home_team_id, away_team_id,
                 match_date, match_time, is_playoff, home_score, away_score,
                 status, api_fixture_id, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        else:
            insert_query = """
                INSERT INTO matches
                (id, home_team, away_team, home_team_id, away_team_id,
                 match_date, match_time, is_playoff, home_score, away_score,
                 status, api_fixture_id, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

        for match in matches:
            cur.execute(
                insert_query,
                (
                    match.get("id"),
                    match.get("home_team"),
                    match.get("away_team"),
                    match.get("home_team_id"),
                    match.get("away_team_id"),
                    match.get("match_date"),
                    match.get("match_time") or "",
                    bool(match.get("is_playoff", False)) if is_postgres() else int(bool(match.get("is_playoff", False))),
                    match.get("home_score"),
                    match.get("away_score"),
                    match.get("status", "scheduled"),
                    match.get("api_fixture_id"),
                    match.get("source")
                )
            )

        conn.commit()
        cur.close()


def load_predictions():
    rows = db_execute(
        """
        SELECT match_id, player, guess_home, guess_away, points, bonus, exact, match_finished
        FROM predictions
        ORDER BY id
        """,
        fetchall=True
    )

    predictions = []
    for row in rows:
        row = normalize_row(row)
        predictions.append({
            "match_id": row["match_id"],
            "player": row["player"],
            "guess_home": int(row["guess_home"]),
            "guess_away": int(row["guess_away"]),
            "points": int(row.get("points") or 0),
            "bonus": int(row.get("bonus") or 0),
            "exact": bool(row.get("exact")),
            "match_finished": bool(row.get("match_finished"))
        })

    return predictions


def save_predictions(predictions):
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM predictions")

        if is_postgres():
            insert_query = """
                INSERT INTO predictions
                (match_id, player, guess_home, guess_away, points, bonus, exact, match_finished)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
        else:
            insert_query = """
                INSERT INTO predictions
                (match_id, player, guess_home, guess_away, points, bonus, exact, match_finished)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """

        for prediction in predictions:
            cur.execute(
                insert_query,
                (
                    prediction.get("match_id"),
                    prediction.get("player"),
                    int(prediction.get("guess_home", 0)),
                    int(prediction.get("guess_away", 0)),
                    int(prediction.get("points", 0)),
                    int(prediction.get("bonus", 0)),
                    bool(prediction.get("exact", False)) if is_postgres() else int(bool(prediction.get("exact", False))),
                    bool(prediction.get("match_finished", False)) if is_postgres() else int(bool(prediction.get("match_finished", False)))
                )
            )

        conn.commit()
        cur.close()


def load_settings():
    api_key = os.environ.get("API_FOOTBALL_KEY")
    if api_key:
        return {"api_football_key": api_key}

    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    return {"api_football_key": ""}


init_db()
players = load_players()


def get_api_fixture_by_id(fixture_id):
    settings = load_settings()
    api_key = settings["api_football_key"]

    url = "https://v3.football.api-sports.io/fixtures"

    headers = {
        "x-apisports-key": api_key
    }

    params = {
        "id": fixture_id
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    fixtures = data.get("response", [])

    if not fixtures:
        return None

    return fixtures[0]

def get_api_fixtures_by_date(match_date):
    settings = load_settings()
    api_key = settings["api_football_key"]

    url = "https://v3.football.api-sports.io/fixtures"

    headers = {
        "x-apisports-key": api_key
    }

    params = {
        "date": match_date
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    return data.get("response", []), data.get("errors", {})



def _normalize_team_name(name):
    return "".join(ch.lower() for ch in (name or "") if ch.isalnum())


def _is_netanya_name(name):
    normalized = _normalize_team_name(name)
    return "נתניה" in normalized or "maccabinetanya" in normalized


def sync_match_order_from_api(match, api_fixture, only_before_kickoff=True):
    """
    Synchronize the local home/away order with API-Football.

    API team IDs are the primary source of truth. For older manually-created
    matches that do not yet have IDs, the function uses the local Netanya name
    only once to determine which side was originally displayed. It then stores
    the official IDs, so every later synchronization is ID-based.

    If the order is reversed, all unfinished predictions are reversed as well,
    preserving the meaning of each user's original prediction. By default no
    change is allowed after kickoff.

    Returns True when the match or its predictions were changed.
    """
    fixture = api_fixture.get("fixture", {})
    teams_data = api_fixture.get("teams", {})
    api_home = teams_data.get("home", {})
    api_away = teams_data.get("away", {})

    api_home_id = api_home.get("id")
    api_away_id = api_away.get("id")
    api_home_name = api_home.get("name")
    api_away_name = api_away.get("name")

    if api_home_id is None or api_away_id is None:
        return False

    fixture_date = fixture.get("date")
    if only_before_kickoff and fixture_date:
        kickoff = datetime.fromisoformat(fixture_date.replace("Z", "+00:00")).astimezone()
        if datetime.now(kickoff.tzinfo) >= kickoff:
            return False

    current_home = match.get("home_team", "")
    current_away = match.get("away_team", "")
    current_home_id = match.get("home_team_id")
    current_away_id = match.get("away_team_id")

    reversed_order = False

    # Preferred path: compare stable API team IDs.
    if current_home_id is not None and current_away_id is not None:
        reversed_order = (
            int(current_home_id) == int(api_away_id)
            and int(current_away_id) == int(api_home_id)
        )
    else:
        # One-time fallback for old/manual rows that predate the ID columns.
        # The API ID still determines Netanya's official side; the local name is
        # used only to identify which side users saw when they made predictions.
        api_netanya_is_home = int(api_home_id) == NETANYA_TEAM_ID
        api_netanya_is_away = int(api_away_id) == NETANYA_TEAM_ID
        local_netanya_is_home = _is_netanya_name(current_home)
        local_netanya_is_away = _is_netanya_name(current_away)

        reversed_order = (
            (api_netanya_is_home and local_netanya_is_away)
            or (api_netanya_is_away and local_netanya_is_home)
        )

    changed = False

    if reversed_order:
        predictions_list = load_predictions()
        predictions_changed = False

        for prediction in predictions_list:
            if prediction.get("match_id") == match.get("id") and not prediction.get("match_finished"):
                prediction["guess_home"], prediction["guess_away"] = (
                    prediction.get("guess_away", 0),
                    prediction.get("guess_home", 0),
                )
                predictions_changed = True

        if predictions_changed:
            save_predictions(predictions_list)

        # Keep local/Hebrew labels and logos, but put them on the official sides.
        match["home_team"], match["away_team"] = current_away, current_home
        changed = True
    elif not current_home or not current_away:
        match["home_team"] = api_home_name or current_home
        match["away_team"] = api_away_name or current_away
        changed = True

    # Persist official IDs on every successful pre-kickoff synchronization.
    # This prevents repeated name-based decisions and makes future checks exact.
    if match.get("home_team_id") != api_home_id:
        match["home_team_id"] = api_home_id
        changed = True

    if match.get("away_team_id") != api_away_id:
        match["away_team_id"] = api_away_id
        changed = True

    return changed

def finish_match_and_calculate(match_to_finish, actual_home, actual_away):
    predictions_list = load_predictions()

    match_id = match_to_finish["id"]

    match_to_finish["home_score"] = actual_home
    match_to_finish["away_score"] = actual_away
    match_to_finish["status"] = "finished"

    for player_name in players:
        player_prediction = None

        for prediction in predictions_list:
            if (
                prediction["player"] == player_name
                and prediction["match_id"] == match_id
            ):
                player_prediction = prediction
                break

        if player_prediction:
            points, is_exact = calculate_match_points(
                player_prediction["guess_home"],
                player_prediction["guess_away"],
                actual_home,
                actual_away,
                match_to_finish["is_playoff"]
            )

            bonus = 0

            if is_exact:
                players[player_name]["streak"] += 1

                if players[player_name]["streak"] == 2:
                    bonus = 4
                    players[player_name]["streak"] = 0
            else:
                players[player_name]["streak"] = 0

            players[player_name]["points"] += points + bonus

            player_prediction["points"] = points
            player_prediction["bonus"] = bonus
            player_prediction["exact"] = is_exact
            player_prediction["match_finished"] = True

        else:
            players[player_name]["streak"] = 0

    save_players()
    save_predictions(predictions_list)

def get_live_match():
    """
    מחזיר משחק שכבר התחיל ועדיין לא סומן כ-finished.
    לא מתבצעת כאן שום משיכת API נוספת.
    """
    matches = load_matches()
    live_matches = []
    now = datetime.now()

    for match in matches:
        if match.get("status") != "scheduled":
            continue

        match_date = match.get("match_date", "")
        match_time = match.get("match_time", "")

        if not match_date:
            continue

        if not match_time:
            match_time = "00:00"

        try:
            match_datetime = datetime.strptime(
                f"{match_date} {match_time}",
                "%Y-%m-%d %H:%M"
            )
        except ValueError:
            continue

        if match_datetime <= now:
            live_matches.append((match_datetime, match))

    if not live_matches:
        return None

    # במקרה חריג שיש יותר ממשחק אחד שלא נסגר,
    # מציגים את המשחק שהתחיל לאחרונה.
    live_matches.sort(key=lambda item: item[0], reverse=True)
    live_match = live_matches[0][1]

    date_obj = datetime.strptime(
        live_match["match_date"],
        "%Y-%m-%d"
    )
    live_match["display_date"] = date_obj.strftime("%d/%m/%Y")

    return live_match

def get_next_match():
    matches = load_matches()
    upcoming_matches = []

    now = datetime.now()

    for match in matches:
        if match.get("status") != "scheduled":
            continue

        match_date = match.get("match_date", "")
        match_time = match.get("match_time", "")

        if match_time:
            match_datetime = datetime.strptime(
                match_date + " " + match_time,
                "%Y-%m-%d %H:%M"
            )
        else:
            match_datetime = datetime.strptime(
                match_date + " 23:59",
                "%Y-%m-%d %H:%M"
            )

        if match_datetime > now:
            upcoming_matches.append((match_datetime, match))

    if not upcoming_matches:
        return None

    upcoming_matches.sort(key=lambda x: x[0])

    next_match = upcoming_matches[0][1]

    date_obj = datetime.strptime(
        next_match["match_date"],
        "%Y-%m-%d"
    )

    next_match["display_date"] = date_obj.strftime("%d/%m/%Y")

    return next_match

def is_match_locked(match):
    match_date = match.get("match_date", "")
    match_time = match.get("match_time", "")

    if not match_date:
        return False

    if not match_time or match_time.strip() == "":
        return False

    match_datetime = datetime.strptime(
        match_date + " " + match_time,
        "%Y-%m-%d %H:%M"
    )

    lock_time = match_datetime - timedelta(hours=1)

    return datetime.now() >= lock_time

def is_admin():
    return session.get("is_admin", False)


def current_user():
    return session.get("username")


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper

def get_leaderboard():
    predictions_list = load_predictions()

    leaderboard_data = []

    for player_name, data in players.items():
        finished_predictions = [
            p for p in predictions_list
            if p.get("player") == player_name and p.get("match_finished") == True
        ]

        total_predictions = len(finished_predictions)
        exact_hits = 0
        successful_predictions = 0
        bonuses = 0

        for prediction in finished_predictions:
            if prediction.get("exact", False):
                exact_hits += 1

            if prediction.get("points", 0) > 0:
                successful_predictions += 1

            if prediction.get("bonus", 0) > 0:
                bonuses += 1

        success_rate = 0
        if total_predictions > 0:
            success_rate = round((successful_predictions / total_predictions) * 100, 1)

        new_data = data.copy()
        new_data["total_predictions"] = total_predictions
        new_data["exact_hits"] = exact_hits
        new_data["successful_predictions"] = successful_predictions
        new_data["bonuses"] = bonuses
        new_data["success_rate"] = success_rate

        leaderboard_data.append((player_name, new_data))

    return sorted(
        leaderboard_data,
        key=lambda x: (
            x[1]["points"],
            x[1]["exact_hits"],
            x[1]["successful_predictions"]
        ),
        reverse=True
)

def get_user_rank(username):
    leaderboard = get_leaderboard()
    for index, item in enumerate(leaderboard, start=1):
        if item[0] == username:
            return index
    return None

@app.context_processor
def inject_user_data():
    username = current_user()
    user_points = None
    user_rank = None

    if username in players:
        user_points = players[username]["points"]
        user_rank = get_user_rank(username)

    return dict(
        is_admin=is_admin(),
        current_user=username,
        user_points=user_points,
        user_rank=user_rank
    )


def get_outcome(home_score, away_score):
    if home_score > away_score:
        return "HOME"
    if away_score > home_score:
        return "AWAY"
    return "DRAW"

def calculate_match_points(guess_home, guess_away, actual_home, actual_away, is_playoff):
    exact_score = guess_home == actual_home and guess_away == actual_away

    correct_direction = (
        get_outcome(guess_home, guess_away)
        ==
        get_outcome(actual_home, actual_away)
    )

    if exact_score:
        return 4 if is_playoff else 3, True

    if correct_direction:
        return 2 if is_playoff else 1, False

    return 0, False

@app.route("/")
@login_required
def home():
    auto_check_results_if_needed()

    username = current_user()
    data = players[username]

    leaderboard_data = get_leaderboard()

    live_match = get_live_match()
    next_match = None if live_match else get_next_match()
    displayed_match = live_match or next_match

    current_prediction = None

    if displayed_match:
        predictions_list = load_predictions()

        for prediction in predictions_list:
            if (
                prediction["player"] == username
                and prediction["match_id"] == displayed_match["id"]
            ):
                current_prediction = prediction
                break

    return render_template(
        "account.html",
        username=username,
        points=data["points"],
        streak=data["streak"],
        rank=get_user_rank(username),
        next_match=next_match,
        live_match=live_match,
        current_prediction=current_prediction,
        leaderboard=leaderboard_data
    )

@app.route("/join", methods=["GET", "POST"])
def join():
    error = None
    success = None

    if request.method == "POST":
        name = request.form.get("new_player", "").strip()
        password = request.form.get("player_password", "")
        confirm_password = request.form.get("confirm_player_password", "")

        if name == "":
            error = "יש להזין שם משתתף"
        elif name in players:
            error = "המשתתף כבר קיים במערכת"
        elif password == "":
            error = "יש להזין סיסמה"
        elif password != confirm_password:
            error = "הסיסמאות לא תואמות"
        else:
            players[name] = {"points": 0, "streak": 0, "password": password}
            save_players()

            session["username"] = name
            session.permanent = False

            return redirect(url_for("home"))

    return render_template("join.html", error=error, success=success)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username not in players:
            error = "המשתתף לא קיים במערכת"
        elif password != players[username].get("password", ""):
            error = "סיסמה שגויה"
        else:
            session["username"] = username
            session.permanent = False
            return redirect(url_for("home"))

    return render_template("login.html", error=error)

@app.route("/leaderboard")
@login_required
def leaderboard():
    leaderboard_data = get_leaderboard()

    return render_template(
        "leaderboard.html",
        leaderboard=leaderboard_data
    )

@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.pop("username", None)

    if request.method == "POST":
        return "", 204

    return redirect(url_for("leaderboard"))


@app.route("/auto-logout", methods=["POST"])
def auto_logout():
    session.pop("username", None)
    return "", 204

@app.route("/rules")
@login_required
def rules():
    return render_template("rules.html")

@app.route("/account", methods=["GET", "POST"])
@login_required
def Home():
    username = current_user()
    data = players[username]

    error = None

    if request.method == "POST":
        password = request.form.get("delete_password", "")

        if password != data.get("password", ""):
            error = "סיסמה שגויה"
        else:
            del players[username]
            save_players()
            session.pop("username", None)
            return redirect(url_for("login"))

    live_match = get_live_match()
    next_match = None if live_match else get_next_match()
    displayed_match = live_match or next_match

    leaderboard_data = get_leaderboard()
    current_prediction = None

    if displayed_match:
        predictions_list = load_predictions()

        for prediction in predictions_list:
            if (
                    prediction["player"] == username
                    and prediction["match_id"] == displayed_match["id"]
            ):
                current_prediction = prediction
                break

    return render_template(
        "account.html",
        username=username,
        points=data["points"],
        streak=data["streak"],
        rank=get_user_rank(username),
        next_match=next_match,
        live_match=live_match,
        current_prediction=current_prediction,
        leaderboard=leaderboard_data,
        error=error
    )

@app.route("/statistics")
@login_required
def statistics():
    username = current_user()
    predictions_list = load_predictions()

    finished_predictions = [
        prediction for prediction in predictions_list
        if prediction.get("match_finished") == True
    ]

    my_predictions = [
        prediction for prediction in finished_predictions
        if prediction["player"] == username
    ]

    def build_stats(predictions):
        total = len(predictions)
        exact_hits = 0
        direction_hits = 0
        bonuses = 0
        total_points = 0

        for prediction in predictions:
            points = prediction.get("points", 0)
            bonus = prediction.get("bonus", 0)
            exact = prediction.get("exact", False)

            total_points += points + bonus

            if exact:
                exact_hits += 1
            elif points > 0:
                direction_hits += 1

            if bonus > 0:
                bonuses += 1

        success_rate = 0

        if total > 0:
            success_rate = round(((exact_hits + direction_hits) / total) * 100, 1)

        return {
            "total": total,
            "exact_hits": exact_hits,
            "direction_hits": direction_hits,
            "bonuses": bonuses,
            "total_points": total_points,
            "success_rate": success_rate
        }

    my_stats = build_stats(my_predictions)
    general_stats = build_stats(finished_predictions)

    exact_by_player = {}

    for prediction in finished_predictions:
        if prediction.get("exact", False):
            player_name = prediction["player"]
            exact_by_player[player_name] = exact_by_player.get(player_name, 0) + 1

    exact_leader = "אין עדיין"
    exact_leader_count = 0

    if exact_by_player:
        exact_leader = max(exact_by_player, key=exact_by_player.get)
        exact_leader_count = exact_by_player[exact_leader]

    return render_template(
        "statistics.html",
        my_stats=my_stats,
        general_stats=general_stats,
        exact_leader=exact_leader,
        exact_leader_count=exact_leader_count
    )

@app.route("/predictions", methods=["GET", "POST"])
@login_required
def predictions():
    username = current_user()

    live_match = get_live_match()
    next_match = get_next_match()

    # המשחק שמוצג בכרטיסיית "המשחק הקרוב"
    match = live_match or next_match
    is_live = live_match is not None

    error = None
    success = None
    active_tab = "current"

    predictions_list = load_predictions()
    matches_list = load_matches()

    # ---------------------------------------------------------
    # שמירת ניחוש - עובד עכשיו עבור כל משחק לפי match_id
    # ---------------------------------------------------------
    if request.method == "POST":
        posted_match_id = request.form.get("match_id", "").strip()
        active_tab = request.form.get("source_tab", "current")

        posted_match = None

        for item in matches_list:
            if item.get("id") == posted_match_id:
                posted_match = item
                break

        if not posted_match:
            error = "המשחק לא נמצא"

        elif posted_match.get("status") != "scheduled":
            error = "לא ניתן לעדכן ניחוש למשחק שהסתיים"

        elif is_match_locked(posted_match):
            error = "הניחושים למשחק הזה כבר ננעלו"

        else:
            guess_home_raw = request.form.get("guess_home", "").strip()
            guess_away_raw = request.form.get("guess_away", "").strip()

            if guess_home_raw == "" or guess_away_raw == "":
                error = "יש למלא תוצאה לשתי הקבוצות"

            else:
                try:
                    guess_home = int(guess_home_raw)
                    guess_away = int(guess_away_raw)

                    if guess_home < 0 or guess_away < 0:
                        error = "לא ניתן להזין תוצאה שלילית"

                    else:
                        existing = None

                        for prediction in predictions_list:
                            if (
                                prediction["player"] == username
                                and prediction["match_id"] == posted_match_id
                            ):
                                existing = prediction
                                break

                        if existing:
                            existing["guess_home"] = guess_home
                            existing["guess_away"] = guess_away
                            success = "הניחוש עודכן בהצלחה"
                        else:
                            predictions_list.append({
                                "match_id": posted_match_id,
                                "player": username,
                                "guess_home": guess_home,
                                "guess_away": guess_away,
                                "points": 0,
                                "bonus": 0,
                                "exact": False,
                                "match_finished": False
                            })

                            success = "הניחוש נשמר בהצלחה"

                        save_predictions(predictions_list)

                except ValueError:
                    error = "יש להזין מספרים תקינים"

    # טוענים שוב אחרי POST כדי שהתצוגה תציג מיד את הנתונים החדשים
    predictions_list = load_predictions()
    matches_list = load_matches()

    # ---------------------------------------------------------
    # כל הניחושים של המשתמש לפי match_id
    # ---------------------------------------------------------
    user_predictions = {}

    for prediction in predictions_list:
        if prediction["player"] == username:
            user_predictions[prediction["match_id"]] = prediction

    # ---------------------------------------------------------
    # המשחק הקרוב / משחק חי
    # ---------------------------------------------------------
    existing_prediction = None
    existing_home = ""
    existing_away = ""
    locked_predictions = []
    locked = False

    if match:
        locked = is_live or is_match_locked(match)

        existing_prediction = user_predictions.get(match["id"])

        if existing_prediction:
            existing_home = existing_prediction["guess_home"]
            existing_away = existing_prediction["guess_away"]

        if locked:
            for player_name in players:
                player_prediction = None

                for prediction in predictions_list:
                    if (
                        prediction["match_id"] == match["id"]
                        and prediction["player"] == player_name
                    ):
                        player_prediction = prediction
                        break

                if player_prediction:
                    locked_predictions.append({
                        "player": player_name,
                        "guessed": True,
                        "guess_home": player_prediction["guess_home"],
                        "guess_away": player_prediction["guess_away"]
                    })
                else:
                    locked_predictions.append({
                        "player": player_name,
                        "guessed": False,
                        "guess_home": None,
                        "guess_away": None
                    })

    # ---------------------------------------------------------
    # כל המשחקים העתידיים, ללא המשחק הקרוב
    # ---------------------------------------------------------
    future_matches = []
    now = datetime.now()

    current_match_id = match["id"] if match else None

    for future_match in matches_list:
        if future_match.get("status") != "scheduled":
            continue

        if future_match.get("id") == current_match_id:
            continue

        match_date = future_match.get("match_date", "")
        match_time = future_match.get("match_time", "")

        if not match_date:
            continue

        try:
            if match_time:
                match_datetime = datetime.strptime(
                    f"{match_date} {match_time}",
                    "%Y-%m-%d %H:%M"
                )
            else:
                match_datetime = datetime.strptime(
                    f"{match_date} 23:59",
                    "%Y-%m-%d %H:%M"
                )

        except ValueError:
            continue

        if match_datetime <= now:
            continue

        date_obj = datetime.strptime(match_date, "%Y-%m-%d")

        future_match["display_date"] = date_obj.strftime("%d/%m/%Y")
        future_match["locked"] = is_match_locked(future_match)

        future_match["prediction"] = user_predictions.get(
            future_match["id"]
        )

        future_match["home_logo"] = TEAM_LOGOS.get(
            future_match["home_team"]
        )

        future_match["away_logo"] = TEAM_LOGOS.get(
            future_match["away_team"]
        )

        future_matches.append((match_datetime, future_match))

    future_matches.sort(key=lambda item: item[0])
    future_matches = [item[1] for item in future_matches]

    return render_template(
        "predictions.html",
        is_live=is_live,
        match=match,
        locked=locked,
        error=error,
        success=success,
        active_tab=active_tab,

        existing_prediction=existing_prediction,
        existing_home=existing_home,
        existing_away=existing_away,
        locked_predictions=locked_predictions,

        future_matches=future_matches,

        home_logo=TEAM_LOGOS.get(match["home_team"]) if match else None,
        away_logo=TEAM_LOGOS.get(match["away_team"]) if match else None
    )

@app.route("/api/save-prediction", methods=["POST"])
@login_required
def save_prediction_api():
    username = current_user()

    data = request.get_json(silent=True) or {}

    match_id = str(data.get("match_id", "")).strip()
    guess_home_raw = data.get("guess_home")
    guess_away_raw = data.get("guess_away")

    # בדיקה שכל הנתונים הגיעו
    if not match_id:
        return jsonify({
            "success": False,
            "message": "המשחק לא נמצא"
        }), 400

    if guess_home_raw is None or guess_away_raw is None:
        return jsonify({
            "success": False,
            "message": "יש למלא תוצאה לשתי הקבוצות"
        }), 400

    # בדיקת תוצאה
    try:
        guess_home = int(guess_home_raw)
        guess_away = int(guess_away_raw)

        if guess_home < 0 or guess_away < 0:
            raise ValueError

    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "message": "יש להזין תוצאה תקינה"
        }), 400

    # חיפוש המשחק
    matches_list = load_matches()

    match = None

    for item in matches_list:
        if str(item.get("id")) == match_id:
            match = item
            break

    if not match:
        return jsonify({
            "success": False,
            "message": "המשחק לא נמצא"
        }), 404

    # אסור לנחש משחק שכבר הסתיים
    if match.get("status") != "scheduled":
        return jsonify({
            "success": False,
            "message": "לא ניתן לעדכן ניחוש למשחק שהסתיים"
        }), 400

    # בדיקת נעילה
    if is_match_locked(match):
        return jsonify({
            "success": False,
            "message": "הניחושים למשחק הזה כבר ננעלו"
        }), 400

    # טעינת הניחושים
    predictions_list = load_predictions()

    existing = None

    for prediction in predictions_list:
        if (
            str(prediction.get("player")) == str(username)
            and str(prediction.get("match_id")) == match_id
        ):
            existing = prediction
            break

    # עדכון ניחוש קיים
    if existing:
        existing["guess_home"] = guess_home
        existing["guess_away"] = guess_away

        message = "הניחוש עודכן בהצלחה"

    # יצירת ניחוש חדש
    else:
        predictions_list.append({
            "match_id": match_id,
            "player": username,
            "guess_home": guess_home,
            "guess_away": guess_away,
            "points": 0,
            "bonus": 0,
            "exact": False,
            "match_finished": False
        })

        message = "הניחוש נשמר בהצלחה"

    save_predictions(predictions_list)

    return jsonify({
        "success": True,
        "message": message,
        "match_id": match_id,
        "guess_home": guess_home,
        "guess_away": guess_away
    })

@app.route("/admin", methods=["GET", "POST"])
def admin():
    error = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "login":
            password = request.form.get("admin_password", "")
            if password == ADMIN_PASSWORD:
                session["is_admin"] = True
                return redirect(url_for("admin"))
            error = "סיסמת מנהל שגויה"

        elif action == "logout":
            session["is_admin"] = False
            return redirect(url_for("leaderboard"))

    total_players = len(players)

    leader_name = "אין עדיין"
    leader_points = 0

    if players:
        leader_name, leader_data = max(
            players.items(),
            key=lambda x: x[1]["points"]
        )
        leader_points = leader_data["points"]

    highest_streak = 0

    if players:
        highest_streak = max(
            player_data["streak"]
            for player_data in players.values()
        )

    return render_template(
        "admin.html",
        error=error,
        total_players=total_players,
        leader_name=leader_name,
        leader_points=leader_points,
        highest_streak=highest_streak
    )
@app.route("/admin/matches", methods=["GET", "POST"])
def admin_matches():
    if not is_admin():
        return redirect(url_for("admin"))

    error = None
    success = None
    matches = load_matches()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "attach_netanya_api":
            attached_count = 0
            checked_dates = {}

            for match in matches:
                if match.get("status") == "finished":
                    continue

                if match.get("api_fixture_id"):
                    continue

                match_date = match.get("match_date")

                if not match_date:
                    continue

                if match_date not in checked_dates:
                    fixtures, api_errors = get_api_fixtures_by_date(match_date)
                    checked_dates[match_date] = {
                        "fixtures": fixtures,
                        "errors": api_errors
                    }

                fixtures = checked_dates[match_date]["fixtures"]

                for api_fixture in fixtures:
                    fixture = api_fixture["fixture"]
                    teams_data = api_fixture["teams"]

                    home_id = teams_data["home"]["id"]
                    away_id = teams_data["away"]["id"]

                    if home_id == NETANYA_TEAM_ID or away_id == NETANYA_TEAM_ID:
                        fixture_datetime = datetime.fromisoformat(
                            fixture["date"].replace("Z", "+00:00")
                        )

                        local_datetime = fixture_datetime.astimezone()

                        match["api_fixture_id"] = fixture["id"]
                        match["source"] = "api"
                        sync_match_order_from_api(match, api_fixture, only_before_kickoff=True)
                        match["match_date"] = local_datetime.strftime("%Y-%m-%d")
                        match["match_time"] = local_datetime.strftime("%H:%M")
                        match["status"] = "scheduled"

                        attached_count += 1
                        break

            save_matches(matches)

            if attached_count > 0:
                success = f"חוברו {attached_count} משחקים ל-API בהצלחה"
            else:
                error = "לא נמצאו משחקי נתניה זמינים ב-API לתאריכים שבמערכת"
        elif action == "import_api_match":
            api_fixture_id = request.form.get("api_fixture_id", "").strip()

            if api_fixture_id == "":
                error = "יש להזין Fixture ID"
            else:
                api_fixture = get_api_fixture_by_id(api_fixture_id)

                if not api_fixture:
                    error = "לא נמצא משחק ב-API"
                else:
                    already_exists = False

                    for match in matches:
                        if str(match.get("api_fixture_id")) == str(api_fixture_id):
                            already_exists = True
                            break

                    if already_exists:
                        error = "המשחק כבר קיים במערכת"
                    else:
                        fixture = api_fixture["fixture"]
                        teams_data = api_fixture["teams"]

                        fixture_datetime = datetime.fromisoformat(
                            fixture["date"].replace("Z", "+00:00")
                        )

                        local_datetime = fixture_datetime.astimezone()

                        new_match = {
                            "id": str(uuid.uuid4()),
                            "api_fixture_id": int(api_fixture_id),
                            "source": "api",
                            "home_team": teams_data["home"]["name"],
                            "away_team": teams_data["away"]["name"],
                            "home_team_id": teams_data["home"]["id"],
                            "away_team_id": teams_data["away"]["id"],
                            "match_date": local_datetime.strftime("%Y-%m-%d"),
                            "match_time": local_datetime.strftime("%H:%M"),
                            "is_playoff": False,
                            "home_score": None,
                            "away_score": None,
                            "status": "scheduled"
                        }

                        matches.append(new_match)
                        save_matches(matches)
                        success = "המשחק יובא מה-API בהצלחה"
        elif action == "check_api_result":
            match_id = request.form.get("match_id")

            match_to_check = None

            for match in matches:
                if match["id"] == match_id:
                    match_to_check = match
                    break

            if not match_to_check:
                error = "המשחק לא נמצא"
            elif match_to_check.get("status") == "finished":
                error = "המשחק כבר הסתיים וחושב"
            elif not match_to_check.get("api_fixture_id"):
                error = "למשחק הזה אין Fixture ID מה-API"
            else:
                api_fixture = get_api_fixture_by_id(
                    match_to_check["api_fixture_id"]
                )

                if not api_fixture:
                    error = "לא הצלחתי למשוך את המשחק מה-API"
                else:
                    fixture = api_fixture["fixture"]
                    goals = api_fixture["goals"]
                    status = fixture["status"]["short"]

                    if status != "FT":
                        error = f"המשחק עדיין לא הסתיים. סטטוס נוכחי: {status}"
                    elif goals["home"] is None or goals["away"] is None:
                        error = "המשחק הסתיים אבל אין עדיין תוצאה זמינה"
                    else:
                        finish_match_and_calculate(
                            match_to_check,
                            goals["home"],
                            goals["away"]
                        )

                        save_matches(matches)

                        success = (
                            f"התוצאה נמשכה מה-API: "
                            f"{match_to_check['home_team']} {goals['home']} - "
                            f"{goals['away']} {match_to_check['away_team']}. "
                            f"הניקוד חושב בהצלחה"
                        )
        if action == "delete_match":
            match_id = request.form.get("match_id")

            matches = [
                match for match in matches
                if match["id"] != match_id
            ]

            save_matches(matches)
            success = "המשחק נמחק בהצלחה"

        elif action == "finish_match":
            match_id = request.form.get("match_id")
            actual_home = int(request.form.get("actual_home"))
            actual_away = int(request.form.get("actual_away"))

            match_to_finish = None

            for match in matches:
                if match["id"] == match_id:
                    match_to_finish = match
                    break

            if not match_to_finish:
                error = "המשחק לא נמצא"
            elif match_to_finish.get("status") == "finished":
                error = "המשחק כבר הסתיים וחושב"
            elif match_to_finish.get("api_fixture_id"):
                error = "משחק שמיובא מה-API צריך להיסגר דרך בדיקת תוצאה מה-API בלבד"
            else:
                predictions_list = load_predictions()

                match_to_finish["home_score"] = actual_home
                match_to_finish["away_score"] = actual_away
                match_to_finish["status"] = "finished"

                for player_name in players:
                    player_prediction = None

                    for prediction in predictions_list:
                        if (
                            prediction["player"] == player_name
                            and prediction["match_id"] == match_id
                        ):
                            player_prediction = prediction
                            break

                    if player_prediction:
                        points, is_exact = calculate_match_points(
                            player_prediction["guess_home"],
                            player_prediction["guess_away"],
                            actual_home,
                            actual_away,
                            match_to_finish["is_playoff"]
                        )

                        bonus = 0

                        if is_exact:
                            players[player_name]["streak"] += 1

                            if players[player_name]["streak"] == 2:
                                bonus = 4
                                players[player_name]["streak"] = 0
                        else:
                            players[player_name]["streak"] = 0

                        players[player_name]["points"] += points + bonus

                        player_prediction["points"] = points
                        player_prediction["bonus"] = bonus
                        player_prediction["exact"] = is_exact
                        player_prediction["match_finished"] = True

                    else:
                        players[player_name]["streak"] = 0

                save_players()
                save_predictions(predictions_list)
                save_matches(matches)

                success = "המשחק הסתיים והניקוד חושב בהצלחה"

        elif action == "create_match":
            home_team = request.form.get("home_team")
            away_team = request.form.get("away_team")
            match_date = request.form.get("match_date")
            match_time = request.form.get("match_time")
            is_playoff = request.form.get("is_playoff") == "on"

            if home_team == away_team:
                error = "לא ניתן ליצור משחק של קבוצה נגד עצמה"
            elif not match_date or not match_time:
                error = "יש להזין תאריך ושעה"
            else:
                new_match = {
                    "id": str(uuid.uuid4()),
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_team_id": None,
                    "away_team_id": None,
                    "match_date": match_date,
                    "match_time": match_time,
                    "is_playoff": is_playoff,
                    "home_score": None,
                    "away_score": None,
                    "status": "scheduled"
                }

                matches.append(new_match)
                save_matches(matches)
                success = "המשחק נוסף בהצלחה"

    return render_template(
        "admin_matches.html",
        teams=teams,
        matches=matches,
        error=error,
        success=success
    )
@app.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    if not is_admin():
        return redirect(url_for("admin"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "adjust_points":
            name = request.form.get("player_name")
            points_change = int(request.form.get("points_change", 0))

            if name in players:
                players[name]["points"] += points_change
                save_players()
        elif action == "delete":
            name = request.form.get("player_to_delete")
            if name in players:
                if session.get("username") == name:
                    session.pop("username", None)
                del players[name]
                save_players()

        elif action == "reset":
            for player in players:
                players[player]["points"] = 0
                players[player]["streak"] = 0

            save_players()
            save_matches([])
            save_predictions([])

    return render_template("admin_users.html", leaderboard=get_leaderboard())

@app.route("/admin/test", methods=["GET", "POST"])
def admin_test():
    if not is_admin():
        return redirect(url_for("admin"))

    result_text = None
    points_text = None
    error = None

    selected_home = "מכבי נתניה"
    selected_away = "מכבי חיפה"
    selected_player = next(iter(players)) if players else ""

    actual_home = 0
    actual_away = 0
    guess_home = 0
    guess_away = 0
    is_playoff = False

    if request.method == "POST":
        selected_home = request.form["home_team"]
        selected_away = request.form["away_team"]
        selected_player = request.form["player"]

        actual_home = int(request.form["actual_home"])
        actual_away = int(request.form["actual_away"])
        guess_home = int(request.form["guess_home"])
        guess_away = int(request.form["guess_away"])
        is_playoff = request.form.get("is_playoff") == "on"

        if selected_home == selected_away:
            error = "לא ניתן לבחור את אותה קבוצה בבית ובחוץ"
        elif selected_player not in players:
            error = "המשתתף שנבחר לא קיים"
        else:
            exact_score = actual_home == guess_home and actual_away == guess_away
            correct_direction = get_outcome(actual_home, actual_away) == get_outcome(guess_home, guess_away)

            exact_points = 4 if is_playoff else 3
            direction_points = 2 if is_playoff else 1

            points = 0
            bonus = 0

            if exact_score:
                points = exact_points
                players[selected_player]["streak"] += 1

                if players[selected_player]["streak"] == 2:
                    bonus = 4
                    players[selected_player]["streak"] = 0
                    points_text = f"פגיעה מדויקת! +{points} וגם בונוס +4"
                else:
                    points_text = f"פגיעה מדויקת! +{points}. רצף: {players[selected_player]['streak']}"

            elif correct_direction:
                points = direction_points
                players[selected_player]["streak"] = 0
                points_text = f"כיוון נכון בלבד! +{points}. הרצף התאפס"
            else:
                players[selected_player]["streak"] = 0
                points_text = "טעות מלאה. +0. הרצף התאפס"

            players[selected_player]["points"] += points + bonus
            save_players()

            result_text = f"{selected_home} {actual_home} - {actual_away} {selected_away}"

    return render_template(
        "admin_test.html",
        teams=teams,
        players=players,
        error=error,
        result_text=result_text,
        points_text=points_text,
        selected_home=selected_home,
        selected_away=selected_away,
        selected_player=selected_player,
        actual_home=actual_home,
        actual_away=actual_away,
        guess_home=guess_home,
        guess_away=guess_away,
        is_playoff=is_playoff
    )

def is_valid_cron_token():
    return request.args.get("token") == AUTO_SYNC_TOKEN


@app.route("/cron/update-match-times")
def cron_update_match_times():
    if not is_valid_cron_token():
        return "Unauthorized", 401

    matches = load_matches()
    today = datetime.now().strftime("%Y-%m-%d")

    updated = 0
    checked = 0

    for match in matches:
        if match.get("status") == "finished":
            continue

        if match.get("match_date") != today:
            continue

        if not match.get("api_fixture_id"):
            continue

        checked += 1

        api_fixture = get_api_fixture_by_id(match["api_fixture_id"])

        if not api_fixture:
            continue

        fixture = api_fixture["fixture"]
        teams_data = api_fixture["teams"]

        fixture_datetime = datetime.fromisoformat(
            fixture["date"].replace("Z", "+00:00")
        )

        local_datetime = fixture_datetime.astimezone()

        order_changed = sync_match_order_from_api(
            match, api_fixture, only_before_kickoff=True
        )
        match["match_date"] = local_datetime.strftime("%Y-%m-%d")
        match["match_time"] = local_datetime.strftime("%H:%M")
        match["source"] = "api"

        updated += 1

    save_matches(matches)

    return f"Update match times done. checked={checked}, updated={updated}"


@app.route("/cron/check-results")
def cron_check_results():
    if not is_valid_cron_token():
        return "Unauthorized", 401

    matches = load_matches()
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now()

    checked = 0
    finished = 0
    skipped = 0

    for match in matches:
        if match.get("status") == "finished":
            skipped += 1
            continue

        if match.get("match_date") != today:
            skipped += 1
            continue

        if not match.get("api_fixture_id"):
            skipped += 1
            continue

        match_time = match.get("match_time", "")

        if not match_time:
            skipped += 1
            continue

        match_datetime = datetime.strptime(
            match["match_date"] + " " + match_time,
            "%Y-%m-%d %H:%M"
        )

        if now < match_datetime:
            skipped += 1
            continue

        checked += 1

        api_fixture = get_api_fixture_by_id(match["api_fixture_id"])

        if not api_fixture:
            continue

        fixture = api_fixture["fixture"]
        goals = api_fixture["goals"]
        status = fixture["status"]["short"]

        if status == "FT" and goals["home"] is not None and goals["away"] is not None:
            finish_match_and_calculate(
                match,
                goals["home"],
                goals["away"]
            )

            finished += 1

    save_matches(matches)

    return f"Check results done. checked={checked}, finished={finished}, skipped={skipped}"

def auto_attach_fixture_if_needed(matches):
    today = datetime.now().strftime("%Y-%m-%d")
    changed = False

    fixtures_cache = {}

    for match in matches:
        if match.get("status") == "finished":
            continue

        if match.get("match_date") != today:
            continue

        if match.get("api_fixture_id"):
            continue

        match_date = match.get("match_date")

        if not match_date:
            continue

        if match_date not in fixtures_cache:
            fixtures, api_errors = get_api_fixtures_by_date(match_date)
            fixtures_cache[match_date] = fixtures

        fixtures = fixtures_cache[match_date]

        for api_fixture in fixtures:
            fixture = api_fixture["fixture"]
            teams_data = api_fixture["teams"]

            home_id = teams_data["home"]["id"]
            away_id = teams_data["away"]["id"]

            if home_id == NETANYA_TEAM_ID or away_id == NETANYA_TEAM_ID:
                fixture_datetime = datetime.fromisoformat(
                    fixture["date"].replace("Z", "+00:00")
                )

                local_datetime = fixture_datetime.astimezone()

                match["api_fixture_id"] = fixture["id"]
                match["source"] = "api"
                sync_match_order_from_api(match, api_fixture, only_before_kickoff=True)
                match["match_date"] = local_datetime.strftime("%Y-%m-%d")
                match["match_time"] = local_datetime.strftime("%H:%M")
                match["status"] = "scheduled"

                changed = True
                break

    return changed

def auto_check_results_if_needed():
    matches = load_matches()
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now()

    changed = False

    if auto_attach_fixture_if_needed(matches):
        changed = True

    for match in matches:
        if match.get("status") == "finished":
            continue

        if match.get("match_date") != today:
            continue

        if not match.get("api_fixture_id"):
            continue

        match_time = match.get("match_time", "")
        if not match_time:
            continue

        match_datetime = datetime.strptime(
            match["match_date"] + " " + match_time,
            "%Y-%m-%d %H:%M"
        )

        # Before kickoff, refresh the official home/away order as well as time.
        # This makes the correction visible to admins and predictors even if the
        # scheduled cron endpoint has not run yet.
        if now < match_datetime:
            api_fixture = get_api_fixture_by_id(match["api_fixture_id"])
            if api_fixture:
                fixture = api_fixture["fixture"]
                fixture_datetime = datetime.fromisoformat(
                    fixture["date"].replace("Z", "+00:00")
                ).astimezone()
                if sync_match_order_from_api(match, api_fixture, only_before_kickoff=True):
                    changed = True
                match["match_date"] = fixture_datetime.strftime("%Y-%m-%d")
                match["match_time"] = fixture_datetime.strftime("%H:%M")
            continue

        if now < match_datetime + timedelta(hours=2):
            continue

        api_fixture = get_api_fixture_by_id(match["api_fixture_id"])
        if not api_fixture:
            continue

        fixture = api_fixture["fixture"]
        goals = api_fixture["goals"]
        status = fixture["status"]["short"]

        if status == "FT" and goals["home"] is not None and goals["away"] is not None:
            finish_match_and_calculate(match, goals["home"], goals["away"])
            changed = True

    if changed:
        save_matches(matches)
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)