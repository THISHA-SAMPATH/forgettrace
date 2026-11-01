
import asyncio
import json
import os
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import asyncpg
from dotenv import load_dotenv

from forgettrace.auth import verify_supabase_access_token
from forgettrace.rls import user_transaction


load_dotenv()


def sign_in(email, password):
    url = os.environ["SUPABASE_URL"].rstrip("/")
    request = Request(
        f"{url}/auth/v1/token?grant_type=password",
        data=json.dumps({
            "email": email,
            "password": password,
        }).encode(),
        headers={
            "apikey": os.environ["SUPABASE_ANON_KEY"],
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlopen(request, timeout=20) as response:
        return json.loads(response.read())["access_token"]


async def authenticate(email, password):
    token = await asyncio.to_thread(sign_in, email, password)
    return await verify_supabase_access_token(
        token, os.environ["SUPABASE_URL"]
    )


async def create_source(pool, user, organization_id, name):
    async with user_transaction(
        pool, user.user_id, user.claims
    ) as conn:
        return await conn.fetchval(
            """
            INSERT INTO public.data_sources
                (organization_id, name, source_type)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            organization_id,
            name,
            "postgres",
        )


async def update_source(pool, user, source_id):
    async with user_transaction(
        pool, user.user_id, user.claims
    ) as conn:
        return await conn.execute(
            """
            UPDATE public.data_sources
            SET name = $1
            WHERE id = $2
            """,
            "Test source updated",
            source_id,
        )


async def delete_source(pool, user, source_id):
    async with user_transaction(
        pool, user.user_id, user.claims
    ) as conn:
        return await conn.execute(
            """
            DELETE FROM public.data_sources
            WHERE id = $1
            """,
            source_id,
        )


async def cleanup_source(pool, user, source_id):
    if source_id is None:
        return

    try:
        await delete_source(pool, user, source_id)
    except Exception:
        print("Warning: A test source may need manual cleanup.")


async def main():
    required = [
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_DB_URL",
        "SUPABASE_TEST_EMAIL",
        "SUPABASE_TEST_PASSWORD",
        "SUPABASE_TEST_EMAIL_B",
        "SUPABASE_TEST_PASSWORD_B",
        "SUPABASE_TEST_ORG_A",
        "SUPABASE_TEST_ORG_B",
    ]

    missing = [key for key in required if not os.getenv(key)]

    if missing:
        print("Missing settings:", ", ".join(missing))
        return

    pool = None
    source_a = None
    source_b = None
    user_a = None
    user_b = None

    try:
        print("Step 1: Authenticating both users...")

        user_a = await authenticate(
            os.environ["SUPABASE_TEST_EMAIL"],
            os.environ["SUPABASE_TEST_PASSWORD"],
        )

        user_b = await authenticate(
            os.environ["SUPABASE_TEST_EMAIL_B"],
            os.environ["SUPABASE_TEST_PASSWORD_B"],
        )

        if user_a.user_id == user_b.user_id:
            raise RuntimeError("Test accounts must be different.")

        print("Both users authenticated.")

        org_a = UUID(os.environ["SUPABASE_TEST_ORG_A"])
        org_b = UUID(os.environ["SUPABASE_TEST_ORG_B"])

        if org_a == org_b:
            raise RuntimeError("The two organization IDs must be different.")

        pool = await asyncpg.create_pool(
            dsn=os.environ["SUPABASE_DB_URL"],
            ssl="require",
            min_size=1,
            max_size=3,
        )

        suffix = uuid4().hex[:8]

        print("Step 2: Creating User A's source...")
        source_a = await create_source(
            pool, user_a, org_a, f"Test Source A {suffix}"
        )
        print("User A source created.")

        print("Step 3: Creating User B's source...")
        source_b = await create_source(
            pool, user_b, org_b, f"Test Source B {suffix}"
        )
        print("User B source created.")

        print("Step 4: Testing cross-organization insert...")
        insert_denied = False

        try:
            async with user_transaction(
                pool, user_a.user_id, user_a.claims
            ) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        INSERT INTO public.data_sources
                            (organization_id, name, source_type)
                        VALUES ($1, $2, $3)
                        """,
                        org_b,
                        f"Unauthorized Source {suffix}",
                        "postgres",
                    )
        except asyncpg.exceptions.InsufficientPrivilegeError:
            insert_denied = True

        print("Cross-organization insert blocked:", insert_denied)

        print("Step 5: Testing cross-organization update...")
        update_result = await update_source(pool, user_a, source_b)
        update_blocked = update_result == "UPDATE 0"

        print("Cross-organization update blocked:", update_blocked)

        print("Step 6: Testing cross-organization delete...")
        delete_result = await delete_source(pool, user_a, source_b)
        delete_blocked = delete_result == "DELETE 0"

        print("Cross-organization delete blocked:", delete_blocked)

        print("Step 7: Testing authorized update...")
        own_update = await update_source(pool, user_a, source_a)
        own_update_allowed = own_update == "UPDATE 1"

        print("Own source update allowed:", own_update_allowed)

        checks = [
            ("Cross-organization insert blocked", insert_denied),
            ("Cross-organization update blocked", update_blocked),
            ("Cross-organization delete blocked", delete_blocked),
            ("Authorized own-source update allowed", own_update_allowed),
        ]

        print("\n--- WRITE ISOLATION RESULTS ---")

        for description, passed in checks:
            print(f"{'PASS' if passed else 'FAIL'}: {description}")

        if all(passed for _, passed in checks):
            print("\nALL WRITE ISOLATION CHECKS PASSED.")
        else:
            print("\nSOME WRITE ISOLATION CHECKS FAILED.")

    except Exception as error:
        print("\nWrite isolation test failed.")
        print("Error type:", type(error).__name__)
        print("Error message:", str(error)[:400])

    finally:
        if pool is not None:
            if user_a is not None:
                await cleanup_source(pool, user_a, source_a)

            if user_b is not None:
                await cleanup_source(pool, user_b, source_b)

            await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
