import libsql_client
import sqlite3
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

TURSO_URL = os.getenv("TURSO_URL").replace("libsql://", "https://")
TURSO_TOKEN = os.getenv("TURSO_TOKEN")

async def migrate():
    local = sqlite3.connect("codigos.db")
    local_cur = local.cursor()

    async with libsql_client.create_client(
        url=TURSO_URL,
        auth_token=TURSO_TOKEN
    ) as client:
        local_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row[0] for row in local_cur.fetchall()]
        print(f"Tables to migrate: {tables}")

        for table in tables:
            local_cur.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
            create_sql = local_cur.fetchone()[0]

            try:
                await client.execute(create_sql)
                print(f"Created table: {table}")
            except Exception as e:
                print(f"Table {table}: {e}")

            local_cur.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in local_cur.fetchall()]

            local_cur.execute(f"SELECT * FROM {table}")
            rows = local_cur.fetchall()

            if rows:
                count = 0
                for row in rows:
                    placeholders = ", ".join(["?" for _ in range(len(row))])
                    col_names = ", ".join(columns)
                    try:
                        await client.execute(
                            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                            list(row)
                        )
                        count += 1
                    except Exception as e:
                        if "UNIQUE" in str(e) or "duplicate" in str(e).lower():
                            pass
                        else:
                            print(f"  Error in {table}: {e}")
                print(f"  Inserted {count}/{len(rows)} rows into {table}")
            else:
                print(f"  No data in {table}")

    local.close()
    print("\nMigration complete!")

asyncio.run(migrate())
