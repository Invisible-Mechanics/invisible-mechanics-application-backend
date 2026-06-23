import asyncio

from sqlalchemy import text

from app.db import Base, engine
from app import models  # noqa: F401


async def main() -> None:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    select table_name, column_name
                    from information_schema.columns
                    where table_schema = 'public'
                    order by table_name, ordinal_position
                    """
                )
            )
        ).mappings().all()

    actual: dict[str, set[str]] = {}
    for row in rows:
        actual.setdefault(row["table_name"], set()).add(row["column_name"])

    has_mismatch = False
    for table_name in sorted(Base.metadata.tables):
        expected = set(Base.metadata.tables[table_name].columns.keys())
        got = actual.get(table_name, set())
        missing = sorted(expected - got)
        extra = sorted(got - expected)
        if missing or extra:
            has_mismatch = True
            print(f"{table_name}: missing={missing} extra={extra}")

    if not has_mismatch:
        print("schema matches SQLAlchemy metadata")


if __name__ == "__main__":
    asyncio.run(main())
