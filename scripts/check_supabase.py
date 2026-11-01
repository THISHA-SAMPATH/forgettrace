
import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

async def check_connection():
    database_url = os.getenv("SUPABASE_DB_URL")

    if not database_url:
        print("Database URL is missing from .env")
        return

    connection = None

    try:
        connection = await asyncpg.connect(
            dsn=database_url,
            ssl="require"
        )

        result = await connection.fetchval("SELECT version()")

        print("ForgetTrace connected to Supabase!")
        print("PostgreSQL connection successful.")

    except Exception as error:
        print("Connection failed:", type(error).__name__)
        print("Check your database URL and connection settings.")

    finally:
        if connection:
            await connection.close()

asyncio.run(check_connection())
