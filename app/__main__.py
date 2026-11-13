"""Start the app: `uv run python -m app`."""

import os

import uvicorn

from app.main import create_app


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    print(f"Mission Control running at http://localhost:{port}")
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
