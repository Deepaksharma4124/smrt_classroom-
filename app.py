import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
DB_PATH = os.environ.get("DB_PATH", "classroom.db")
API_KEY = os.environ.get("API_KEY", "change-this-demo-key")

def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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

def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        supplied = request.headers.get("X-API-Key", "")
        if not API_KEY or supplied != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper

@app.get("/")
def dashboard():
    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Smart Classroom Monitor</title>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
      <style>
        body {font:16px Arial; max-width:900px; margin:30px auto;
              padding:0 16px; background:#f4f7fb; color:#172033}
        .cards {display:flex; gap:16px; flex-wrap:wrap}
        .card {background:white; padding:20px; border-radius:12px;
               flex:1; min-width:180px}
        canvas {background:white; padding:12px; margin-top:20px;
                border-radius:12px}
      </style>
    </head>
    <body>
      <h1>Smart Classroom Cloud Monitor</h1>
      <p>Live classroom environment readings</p>
      <div class="cards">
        <div class="card">Temperature
          <h2 id="temp">Loading...</h2></div>
        <div class="card">Humidity
          <h2 id="humidity">Loading...</h2></div>
        <div class="card">Status
          <h2 id="status">Loading...</h2></div>
      </div>
      <canvas id="chart"></canvas>
      <p id="updated">Waiting for sensor data...</p>
      <script>
        const ctx = document.getElementById('chart');
        const chart = new Chart(ctx, {
          type: 'line',
          data: {labels: [], datasets: [
            {label: 'Temperature (°C)', data: [], yAxisID: 'y'},
            {label: 'Humidity (%)', data: [], yAxisID: 'y1'}
          ]},
          options: {responsive:true, scales: {
            y: {type:'linear', position:'left'},
            y1: {type:'linear', position:'right',
                 min:0, max:100, grid:{drawOnChartArea:false}}
          }}
        });

        async function refresh() {
          try {
            const response = await fetch('/api/history?limit=50');
            if (!response.ok) throw new Error('API unavailable');
            const rows = await response.json();
            if (!rows.length) {
              document.getElementById('status').textContent =
                'Waiting for data';
              return;
            }
            const latest = rows[rows.length - 1];
            document.getElementById('temp').textContent =
              latest.temperature.toFixed(1) + ' °C';
            document.getElementById('humidity').textContent =
              latest.humidity.toFixed(1) + ' %';
            document.getElementById('status').textContent =
              latest.temperature >= 30 ? 'High temperature' : 'Monitoring';
            document.getElementById('updated').textContent =
              'Last reading: ' + latest.timestamp;
            chart.data.labels = rows.map(r =>
              new Date(r.timestamp).toLocaleTimeString());
            chart.data.datasets[0].data = rows.map(r => r.temperature);
            chart.data.datasets[1].data = rows.map(r => r.humidity);
            chart.update();
          } catch (e) {
            document.getElementById('status').textContent =
              'Waiting for connection';
          }
        }
        refresh();
        setInterval(refresh, 5000);
      </script>
    </body>
    </html>
    """)

@app.post("/api/readings")
@require_api_key
def add_reading():
    data = request.get_json(silent=True) or {}

    try:
        temperature = float(data["temperature"])
        humidity = float(data["humidity"])
        device_id = str(data.get("device_id", "classroom-01"))[:64]

        if not (-10 <= temperature <= 70 and 0 <= humidity <= 100):
            return jsonify({"error": "Sensor values out of range"}), 400

        timestamp = datetime.now(timezone.utc).isoformat()

        with connect_db() as conn:
            cursor = conn.execute(
                """INSERT INTO readings
                   (timestamp, temperature, humidity, device_id)
                   VALUES (?, ?, ?, ?)""",
                (timestamp, temperature, humidity, device_id)
            )
            reading_id = cursor.lastrowid

        return jsonify({
            "message": "Reading saved",
            "id": reading_id,
            "timestamp": timestamp
        }), 201

    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid sensor payload"}), 400

@app.get("/api/history")
def history():
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 500)
    except ValueError:
        return jsonify({"error": "Invalid limit"}), 400

    with connect_db() as conn:
        rows = conn.execute(
            "SELECT * FROM readings ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()

    # Return oldest to newest for chart plotting.
    return jsonify([dict(row) for row in reversed(rows)])

@app.get("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
