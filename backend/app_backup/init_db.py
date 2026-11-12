"""CLI script to initialize the SQLite database schema reproducibly."""

import sys
from backend.app.database import engine, init_db


def main() -> None:
    """Create all registered database tables."""
    print("Initializing PayLater Shield database schema...")
    try:
        init_db(engine)
        print("Database schema successfully created!")
    except Exception as exc:
        print(f"Database initialization failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

