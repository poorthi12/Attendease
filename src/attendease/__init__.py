"""Command-line entry point for the shared AttendEase FastAPI application."""


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
