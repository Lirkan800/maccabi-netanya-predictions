from flask import Flask, render_template, request, redirect, url_for, session
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
    "בית\"ר י-ם": "ביתר ירושלים.png",
    "בית\"ר ירושלים": "ביתר ירושלים.png",
    "מכבי חיפה": "מכבי חיפה.png",
    "מכבי ת\"א": "מכבי תל אביב.png",
    "הפועל חיפה": "הפועל חיפה.png",
    "הפועל ב\"ש": "הפועל באר שבע.png",
    "הפועל ת\"א": "הפועל תל אביב.png",
    "מכבי פ\"ת": "מכבי פתח תקווה.png",
    "הפועל פ\"ת": "הפועל פתח תקווה.png",
    "הפועל ר\"ג": "הפועל רמת גן.png",
    "הפועל ק\"ש": "הפועל קריית שמונה.png",
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
        SELECT id, home_team, away_team, match_date, match_time, is_playoff,
               home_score, away_score, status, api_fixture_id, source
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
                (id, home_team, away_team, match_date, match_time, is_playoff,
                 home_score, away_score, status, api_fixture_id, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        else:
            insert_query = """
                INSERT INTO matches
                (id, home_team, away_team, match_date, match_time, is_playoff,
                 home_score, away_score, status, api_fixture_id, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

        for match in matches:
            cur.execute(
                insert_query,
                (
                    match.get("id"),
                    match.get("home_team"),
                    match.get("away_team"),
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

                if players[player_name]["streak"] == 3:
                    bonus = 6
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
        return 3 if is_playoff else 2, True

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
    next_match = get_next_match()

    return render_template(
        "account.html",
        username=username,
        points=data["points"],
        streak=data["streak"],
        rank=get_user_rank(username),
        next_match=next_match,
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

@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("leaderboard"))

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

    return render_template(
        "account.html",
        username=username,
        points=data["points"],
        streak=data["streak"],
        rank=get_user_rank(username),
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
    match = get_next_match()

    error = None
    success = None

    existing_prediction = None
    existing_home = ""
    existing_away = ""

    if not match:
        return render_template(
            "predictions.html",
            match=None,
            locked=False,
            error=None,
            success=None,
            existing_prediction=None,
            existing_home="",
            existing_away=""
        )

    predictions_list = load_predictions()
    locked = is_match_locked(match)

    for prediction in predictions_list:
        if prediction["player"] == username and prediction["match_id"] == match["id"]:
            existing_prediction = prediction
            existing_home = prediction["guess_home"]
            existing_away = prediction["guess_away"]
            break

    if request.method == "POST":
        if locked:
            error = "הניחושים למשחק הזה כבר ננעלו"
        else:
            guess_home_raw = request.form.get("guess_home", "").strip()
            guess_away_raw = request.form.get("guess_away", "").strip()

            if guess_home_raw == "" or guess_away_raw == "":
                error = "יש למלא תוצאה לשתי הקבוצות"
            else:
                guess_home = int(guess_home_raw)
                guess_away = int(guess_away_raw)

                if existing_prediction:
                    existing_prediction["guess_home"] = guess_home
                    existing_prediction["guess_away"] = guess_away
                    success = "הניחוש עודכן בהצלחה"
                else:
                    predictions_list.append({
                        "match_id": match["id"],
                        "player": username,
                        "guess_home": guess_home,
                        "guess_away": guess_away
                    })
                    success = "הניחוש נשמר בהצלחה"

                save_predictions(predictions_list)

                existing_home = guess_home
                existing_away = guess_away
                existing_prediction = True

    return render_template(
        "predictions.html",
        match=match,
        locked=locked,
        error=error,
        success=success,
        existing_prediction=existing_prediction,
        existing_home=existing_home,
        existing_away=existing_away,
        home_logo=TEAM_LOGOS.get(match["home_team"]),
        away_logo=TEAM_LOGOS.get(match["away_team"])
    )
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
                        match["home_team"] = teams_data["home"]["name"]
                        match["away_team"] = teams_data["away"]["name"]
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

                            if players[player_name]["streak"] == 3:
                                bonus = 6
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

            exact_points = 3 if is_playoff else 2
            direction_points = 2 if is_playoff else 1

            points = 0
            bonus = 0

            if exact_score:
                points = exact_points
                players[selected_player]["streak"] += 1

                if players[selected_player]["streak"] == 3:
                    bonus = 6
                    players[selected_player]["streak"] = 0
                    points_text = f"פגיעה מדויקת! +{points} וגם בונוס +6"
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

        match["home_team"] = teams_data["home"]["name"]
        match["away_team"] = teams_data["away"]["name"]
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

def auto_check_results_if_needed():
    matches = load_matches()
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now()

    changed = False

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

        # בודק רק אחרי שעברו לפחות שעתיים מתחילת המשחק
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
