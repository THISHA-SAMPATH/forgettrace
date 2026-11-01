
import asyncio
import json
import os
from urllib.request import Request, urlopen
from uuid import uuid4

import asyncpg
from dotenv import load_dotenv

from forgettrace.auth import verify_supabase_access_token
from forgettrace.rls import user_transaction


load_dotenv()


def sign_in(email, password):
    """Sign in and return an access token."""
    url = os.environ["SUPABASE_URL"].rstrip("/")
    api_key = os.environ["SUPABASE_ANON_KEY"]

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


async def authenticate_user(email, password):
    token = await asyncio.to_thread(sign_in, email, password)

    return await verify_supabase_access_token(
        token,
        os.environ["SUPABASE_URL"],
    )


async def create_test_organization(pool, user, name):
    async with user_transaction(
        pool, user.user_id, user.claims
    ) as connection:
        organization_id = await connection.fetchval(
            "SELECT private.create_organization($1)",
            name,
        )

    return organization_id


async def can_see_organization(pool, user, organization_id):
    async with user_transaction(
        pool, user.user_id, user.claims
    ) as connection:
        return await connection.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM public.organizations
                WHERE id = $1
            )
            """,
            organization_id,
        )


async def main():
    required = [
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_DB_URL",
        "SUPABASE_TEST_EMAIL",
        "SUPABASE_TEST_PASSWORD",
        "SUPABASE_TEST_EMAIL_B",
        "SUPABASE_TEST_PASSWORD_B",
    ]

    missing = [key for key in required if not os.getenv(key)]

    if missing:
        print("Missing .env settings:", ", ".join(missing))
        return

    pool = None

    try:
        print("Step 1: Authenticating User A...")
        user_a = await authenticate_user(
            os.environ["SUPABASE_TEST_EMAIL"],
            os.environ["SUPABASE_TEST_PASSWORD"],
        )
        print("User A authenticated.")

        print("Step 2: Authenticating User B...")
        user_b = await authenticate_user(
            os.environ["SUPABASE_TEST_EMAIL_B"],
            os.environ["SUPABASE_TEST_PASSWORD_B"],
        )
        print("User B authenticated.")

        if user_a.user_id == user_b.user_id:
            raise RuntimeError("Both accounts resolved to the same user.")

        print("Step 3: Connecting to PostgreSQL...")
        pool = await asyncpg.create_pool(
            dsn=os.environ["SUPABASE_DB_URL"],
            ssl="require",
            min_size=1,
            max_size=3,
        )

        suffix = uuid4().hex[:8]

        print("Step 4: Creating User A's test organization...")
        org_a = await create_test_organization(
            pool, user_a, f"Isolation Test A {suffix}"
        )
        print("User A organization created.")

        print("Step 5: Creating User B's test organization...")
        org_b = await create_test_organization(
            pool, user_b, f"Isolation Test B {suffix}"
        )
        print("User B organization created.")

        print("Step 6: Checking User A's access...")
        a_sees_own = await can_see_organization(pool, user_a, org_a)
        a_sees_b = await can_see_organization(pool, user_a, org_b)

        print("User A sees own organization:", a_sees_own)
        print("User A sees User B organization:", a_sees_b)

        print("Step 7: Checking User B's access...")
        b_sees_own = await can_see_organization(pool, user_b, org_b)
        b_sees_a = await can_see_organization(pool, user_b, org_a)

        print("User B sees own organization:", b_sees_own)
        print("User B sees User A organization:", b_sees_a)

        checks = [
            ("User A can see own organization", a_sees_own),
            ("User A cannot see User B organization", not a_sees_b),
            ("User B can see own organization", b_sees_own),
            ("User B cannot see User A organization", not b_sees_a),
        ]

        print("\n--- ISOLATION TEST RESULTS ---")

        for description, passed in checks:
            print(f"{'PASS' if passed else 'FAIL'}: {description}")

        if all(passed for _, passed in checks):
            print("\nALL ORGANIZATION ISOLATION CHECKS PASSED.")
        else:
            print("\nORGANIZATION ISOLATION TEST FAILED.")

    except Exception as error:
        print("\nIsolation test failed.")
        print("Error type:", type(error).__name__)
        print("Error message:", str(error)[:500])
        print("Do not share credentials, tokens, or database URLs.")

    finally:
        if pool is not None:
            await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
