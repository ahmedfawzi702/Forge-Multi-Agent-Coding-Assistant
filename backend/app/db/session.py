from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def create_database(url: str) -> tuple[Engine, sessionmaker[Session]]:
    sqlite = url.startswith("sqlite")
    engine = create_engine(url, connect_args={"check_same_thread": False} if sqlite else {},
                           pool_pre_ping=True)
    if sqlite:
        @event.listens_for(engine, "connect")
        def configure_sqlite(connection: object, _: object) -> None:
            cursor = connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return engine, sessionmaker(engine, expire_on_commit=False)
