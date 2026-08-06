# One image, two Render services (see render.yaml): each service overrides
# CMD with its own start command (uvicorn for the API, bokeh serve for the
# UI) rather than maintaining two separate Dockerfiles that would drift.
#
# Uses requirements-web.txt, not requirements.txt -- see that file's
# header for why (no gymnasium/stable-baselines3/torch in the deploy
# image; those are only needed for local RL training, not for serving).
FROM python:3.11-slim

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY . .

ENV PYTHONUNBUFFERED=1

# Default to the API; render.yaml's frontend service overrides this with
# its own dockerCommand (bokeh serve).
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
