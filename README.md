# Affinity to Markdown

Converts Affinity Publisher `.afpub` files to clean Markdown.

## Live App

https://afpub-converter-z2m7tlw3yq-ue.a.run.app

## Project Structure

- `main.py` — FastAPI web server
- `afpub_to_markdown.py` — Core extraction engine
- `templates/` — Book template styles.yaml files
- `static/` — Frontend UI
- `Dockerfile` — Container config for Cloud Run
