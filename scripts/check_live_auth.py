
import asyncio
import json
import os
from urllib.request import Request, urlopen
from urllib.error import URLError

import asyncpg
from dotenv import load_dotenv

from forgettrace.auth import verify_supabase_access_token
from forgettrace.rls import user_transaction


load_dotenv()


def sign_in():
    """Sign in without displaying or logging credentials."""
    url = os.environ["SUPABASE_URL"].rstrip("/")
    api_key = os.environ["SUPABASE_ANON_KEY"]
    email = os.environ["SUPABASE_TEST_EMAIL"]
    password = os.environ["SUPABASE_TEST_PASSWORD"]

    request = Request(
        f"{url}/auth/v1/token?grant_type=password",
        data=json.dumps({
            "email": email,
            "password": password,
        }).encode("utf-8"),
        headers={
            "apikey": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlopen(request, timeout=20) as response:
        result = json.loads(response.read())

    return result["access_token"]


async def main():
    required = [
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_TEST_EMAIL",
        "SUPABASE_TEST_PASSWORD",
        "SUPABASE_DB_URL",
    ]

    missing = [name for name in required if not os.getenv(name)]

    if missing:
        print("Missing .env settings:", ", ".join(missing))
        return

    pool = None

    try:
        print("Step 1: Signing in to Supabase...")
        token = await asyncio.to_thread(sign_in)
        print("Supabase sign-in successful.")

        print("Step 2: Verifying JWT...")
        user = await verify_supabase_access_token(
            token,
            os.environ["SUPABASE_URL"],
        )

        print("JWT verification successful.")
        print("Verified user ID:", user.user_id)

        print("Step 3: Connecting to PostgreSQL...")
        pool = await asyncpg.create_pool(
            dsn=os.environ["SUPABASE_DB_URL"],
            ssl="require",
            min_size=1,
            max_size=2,
        )

        print("Step 4: Testing transaction and RLS identity...")

        async with user_transaction(
            pool,
            user.user_id,
            user.claims,
        ) as connection:

            result = await connection.fetchrow("""
                SELECT
                    session_user,
                    current_user,
                    private.current_user_id() AS jwt_user_id
            """)

            database_user_id = result["jwt_user_id"]

            if str(database_user_id) != str(user.user_id):
                raise RuntimeError(
                    "Database identity does not match JWT."
                )

            if result["current_user"] != "forgettrace_app":
                raise RuntimeError(
                    "Unexpected active database role."
                )

            print("Database identity matches verified JWT.")
            print("Login role:", result["session_user"])
            print("Active role:", result["current_user"])
            print("RLS user context verified.")

        print("\nALL LIVE AUTHENTICATION CHECKS PASSED.")

    except URLError as error:
        print("\nNetwork connection failed.")
        print("Reason type:", type(error.reason).__name__)
        print("Reason:", str(error.reason)[:300])

    except Exception as error:
        print("\nLive authentication test failed.")
        print("Error type:", type(error).__name__)
        print("Error message:", str(error)[:500])
        print("No credentials or tokens were printed.")

    finally:
        if pool is not None:
            await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
