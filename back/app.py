"""Entrypoint: `gunicorn app:app` o `python app.py`. La app vive en el paquete resilio."""
import os

from resilio import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
