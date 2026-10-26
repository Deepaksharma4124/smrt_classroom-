
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

# Configuration
DB_PATH = os.environ.get("DB_PATH", "classroom.db")
API_KEY = os.environ.get("API_KEY", "")


# Database connection
def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


# Create database table
def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                temperature REAL NOT NULL,
                humidity REAL NOT NULL,
                device_id TEXT NOT NULL
            )
        """)


init_db()


# API key authentication
def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not API_KEY:
            app.logger.error("API_KEY is not configured.")
            return jsonify({
                "error": "Server API key is not configured"
            }), 503

        supplied_key = request.headers.get("X-API-Key", "")

        if supplied_key != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401

        return fn(*args, **kwargs)

    return wrapper


# Dashboard
@app.get("/")
def dashboard():
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>Smart Classroom Monitor</title>

        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 1000px;
                margin: 25px auto;
                padding: 0 16px;
                background: #f4f7fb;
                color: #172033;
            }

            .cards {
                display: flex;
                gap: 16px;
                flex-wrap: wrap;
            }

            .card {
                background: white;
                padding: 20px;
                border-radius: 12px;
                flex: 1;
                min-width: 180px;
                box-shadow: 0 2px 8px #0000000d;
            }

            .value {
                font-size: 28px;
                margin-bottom: 5px;
            }

            .chart-container {
                background: white;
                margin-top: 20px;
                padding: 16px;
                border-radius: 12px;
            }

            #updated {
                color: #526078;
                font-size: 14px;
            }
        </style>
    </head>

    <body>
        <h1>Smart Classroom Cloud Monitor</h1>
        <p>Classroom temperature and humidity monitoring</p>

        <div class="cards">
            <div class="card">
                Temperature
                <h2 class="value" id="temp">Loading...</h2>
            </div>

            <div class="card">
                Humidity
                <h2 class="value" id="humidity">Loading...</h2>
            </div>

            <div class="card">
                Status
                <h2 id="status">Connecting...</h2>
            </div>
        </div>

        <div class="chart-container">
            <canvas id="chart"></canvas>
        </div>

        <p id="updated">Waiting for sensor readings...</p>

        <script>
            const chart = new Chart(
                document.getElementById("chart"),
                {
                    type: "line",
                    data: {
                        labels: [],
                        datasets: [
                            {
                                label: "Temperature (°C)",
                                data: [],
                                yAxisID: "y",
                                tension: 0.2
                            },
                            {
                                label: "Humidity (%)",
                                data: [],
                                yAxisID: "y1",
                                tension: 0.2
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        scales: {
                            y: {
                                type: "linear",
                                position: "left",
                                title: {
                                    display: true,
                                    text: "Temperature (°C)"
                                }
                            },
                            y1: {
                                type: "linear",
                                position: "right",
                                min: 0,
                                max: 100,
                                title: {
                                    display: true,
                                    text: "Humidity (%)"
                                },
                                grid: {
                                    drawOnChartArea: false
                                }
                            }
                        }
                    }
                }
            );

            async function refreshDashboard() {
                const status = document.getElementById("status");

                try {
                    const response = await fetch(
                        "/api/history?limit=50",
                        { cache: "no-store" }
                    );

                    if (!response.ok) {
                        throw new Error("History API unavailable");
                    }

                    const rows = await response.json();

                    if (rows.length === 0) {
                        status.textContent = "Waiting for data";
                        document.getElementById("updated").textContent =
                            "No readings received yet.";
                        return;
                    }

                    const latest = rows[rows.length - 1];

                    document.getElementById("temp").textContent =
                        Number(latest.temperature).toFixed(1) + " °C";

                    document.getElementById("humidity").textContent =
                        Number(latest.humidity).toFixed(1) + " %";

                    status.textContent =
                        Number(latest.temperature) >= 30
                            ? "High temperature"
                            : "Monitoring";

                    document.getElementById("updated").textContent =
                        "Last reading: " + latest.timestamp +
                        " | Device: " + latest.device_id;

                    chart.data.labels = rows.map(row =>
                        new Date(row.timestamp).toLocaleTimeString()
                    );

                    chart.data.datasets[0].data = rows.map(
                        row => Number(row.temperature)
                    );

                    chart.data.datasets[1].data = rows.map(
                        row => Number(row.humidity)
                    );

                    chart.update();
                } catch (error) {
                    status.textContent = "Connection error";
                    console.error("Dashboard error:", error);
                }
            }

            refreshDashboard();
            setInterval(refreshDashboard, 5000);
        </script>
    </body>
    </html>
    """)


# Receive sensor readings from Python uploader
@app.post("/api/readings")
@require_api_key
def add_reading():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required"}), 400

    try:
        temperature = float(data["temperature"])
        humidity = float(data["humidity"])
        device_id = str(
            data.get("device_id", "classroom-01")
        ).strip()[:64]

        if not (-10 <= temperature <= 70):
            return jsonify({
                "error": "Temperature is out of range"
            }), 400

        if not (0 <= humidity <= 100):
            return jsonify({
                "error": "Humidity is out of range"
            }), 400

        if not device_id:
            device_id = "classroom-01"

    except (KeyError, TypeError, ValueError):
        return jsonify({
            "error": "Invalid temperature or humidity"
        }), 400

    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        with connect_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO readings
                (timestamp, temperature, humidity, device_id)
                VALUES (?, ?, ?, ?)
                """,
                (timestamp, temperature, humidity, device_id)
            )

            reading_id = cursor.lastrowid

        return jsonify({
            "message": "Reading saved",
            "id": reading_id,
            "timestamp": timestamp
        }), 201

    except sqlite3.Error:
        app.logger.exception("Database write failed")
        return jsonify({"error": "Database error"}), 500


# Return recent readings for the dashboard
@app.get("/api/history")
def history():
    try:
        limit = int(request.args.get("limit", 50))
        limit = min(max(limit, 1), 500)
    except ValueError:
        return jsonify({"error": "Invalid limit"}), 400

    try:
        with connect_db() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, temperature, humidity, device_id
                FROM readings
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()

        # Oldest to newest for the chart
        return jsonify([dict(row) for row in reversed(rows)])

    except sqlite3.Error:
        app.logger.exception("Database read failed")
        return jsonify({"error": "Database error"}), 500


# Render health check
@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)

