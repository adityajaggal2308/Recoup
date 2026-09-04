"""
server.py — the single deployable entry point.

Serves static/index.html at "/" and exposes POST /api/run, which runs the
full agent pipeline (src/agent.py) and returns one JSON result. Serving the
frontend and the API from the same Flask app avoids CORS entirely and keeps
deployment to one Render web service.

Run locally:
    export ANTHROPIC_API_KEY=sk-ant-...
    python server.py
    # visit http://localhost:5000

Production (Render): gunicorn server:app — see Procfile / render.yaml.
"""
import os
import sys
import traceback

from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from agent import run_pipeline  # noqa: E402
from data_loader import PaymentsLoadError  # noqa: E402

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/run", methods=["POST"])
def api_run():
    try:
        result = run_pipeline()
        return jsonify({"ok": True, "data": result})
    except PaymentsLoadError as e:
        return jsonify({"ok": False, "error": f"Data error: {e}"}), 500
    except Exception as e:
        # Never let an unexpected error surface as a bare 500 with a stack
        # trace to the client — log it server-side, return clean JSON.
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"Unexpected server error: {e}"}), 500


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "status": "healthy"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
