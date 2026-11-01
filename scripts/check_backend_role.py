
import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

async def main():
    connection = None
    stage = "connecting"

    try:
        dsn = os.getenv("SUPABASE_DB_URL")
        if not dsn:
            print("SUPABASE_DB_URL is missing.")
            return

        connection = await asyncpg.connect(dsn=dsn, ssl="require")
        print("Connection successful.")

        stage = "checking login"
        identity = await connection.fetchrow(
            "SELECT session_user, current_user"
        )
        print("Login role:", identity["session_user"])
        print("Current role:", identity["current_user"])

        stage = "switching role"
        async with connection.transaction():
            await connection.execute(
                "SET LOCAL ROLE forgettrace_app"
            )
            print("Role switch successful.")

            stage = "checking JWT helper"
            user_id = await connection.fetchval(
                "SELECT private.current_user_id()"
            )
            print("JWT helper successful.")
            print("JWT user ID:", user_id)

        print("ALL CHECKS PASSED")

    except Exception as error:
        print("Failed at:", stage)
        print("Error type:", type(error).__name__)
        print("Error detail:", str(error))

    finally:
        if connection:
            await connection.close()

asyncio.run(main())
