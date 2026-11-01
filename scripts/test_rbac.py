
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


async def main():
    pool = None
    source_id = None
    dataset_id = None
    owner = None
    analyst = None

    try:
        print("Step 1: Authenticating Owner and Analyst...")

        owner = await authenticate(
            os.environ["SUPABASE_TEST_EMAIL"],
            os.environ["SUPABASE_TEST_PASSWORD"],
        )

        analyst = await authenticate(
            os.environ["SUPABASE_TEST_EMAIL_B"],
            os.environ["SUPABASE_TEST_PASSWORD_B"],
        )

        org_id = UUID(os.environ["SUPABASE_TEST_ORG_A"])

        pool = await asyncpg.create_pool(
            dsn=os.environ["SUPABASE_DB_URL"],
            ssl="require",
            min_size=1,
            max_size=3,
        )

        suffix = uuid4().hex[:8]

        print("Both users authenticated.")

        print("Step 2: Owner creates a test data source...")

        async with user_transaction(
            pool, owner.user_id, owner.claims
        ) as conn:
            source_id = await conn.fetchval(
                """
                INSERT INTO public.data_sources
                    (organization_id, name, source_type)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                org_id,
                f"RBAC Test Source {suffix}",
                "postgres",
            )

        print("Test source created.")

        print("Step 3: Testing Analyst source creation...")

        source_creation_blocked = False

        try:
            async with user_transaction(
                pool, analyst.user_id, analyst.claims
            ) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        INSERT INTO public.data_sources
                            (organization_id, name, source_type)
                        VALUES ($1, $2, $3)
                        """,
                        org_id,
                        f"Analyst Unauthorized Source {suffix}",
                        "postgres",
                    )

        except asyncpg.exceptions.InsufficientPrivilegeError:
            source_creation_blocked = True

        print(
            "Analyst blocked from creating source:",
            source_creation_blocked,
        )

        print("Step 4: Testing Analyst dataset creation...")

        dataset_allowed = False

        async with user_transaction(
            pool, analyst.user_id, analyst.claims
        ) as conn:
            dataset_id = await conn.fetchval(
                """
                INSERT INTO public.datasets
                    (organization_id, source_id, external_id, table_name)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                org_id,
                source_id,
                f"rbac-test-{suffix}",
                "rbac_test_table",
            )

            dataset_allowed = dataset_id is not None

        print("Analyst allowed to create dataset:", dataset_allowed)

        checks = [
            ("Analyst cannot create data sources", source_creation_blocked),
            ("Analyst can create datasets", dataset_allowed),
        ]

        print("\n--- RBAC TEST RESULTS ---")

        for description, passed in checks:
            print(f"{'PASS' if passed else 'FAIL'}: {description}")

        if all(passed for _, passed in checks):
            print("\nALL RBAC CHECKS PASSED.")
        else:
            print("\nSOME RBAC CHECKS FAILED.")

    except Exception as error:
        print("\nRBAC test failed.")
        print("Error type:", type(error).__name__)
        print("Error message:", str(error)[:400])

    finally:
        if pool is not None:
            if dataset_id is not None and owner is not None:
                try:
                    async with user_transaction(
                        pool, owner.user_id, owner.claims
                    ) as conn:
                        await conn.execute(
                            "DELETE FROM public.datasets WHERE id = $1",
                            dataset_id,
                        )
                except Exception:
                    print("Warning: Test dataset may need manual cleanup.")

            if source_id is not None and owner is not None:
                try:
                    async with user_transaction(
                        pool, owner.user_id, owner.claims
                    ) as conn:
                        await conn.execute(
                            "DELETE FROM public.data_sources WHERE id = $1",
                            source_id,
                        )
                except Exception:
                    print("Warning: Test source may need manual cleanup.")

            await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
