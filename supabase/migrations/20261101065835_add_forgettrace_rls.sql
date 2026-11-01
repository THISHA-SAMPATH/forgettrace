
BEGIN;

-- 1. Create a restricted application role.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'forgettrace_app'
    ) THEN
        CREATE ROLE forgettrace_app
            NOLOGIN NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

ALTER ROLE forgettrace_app
    NOLOGIN NOINHERIT NOBYPASSRLS;

-- 2. Private schema and permissions.
CREATE SCHEMA IF NOT EXISTS private AUTHORIZATION postgres;
ALTER SCHEMA private OWNER TO postgres;

REVOKE ALL ON SCHEMA private FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA private TO forgettrace_app;

GRANT USAGE ON SCHEMA public TO forgettrace_app;

-- 3. Read the user ID from verified JWT claims.
-- The Python backend must verify the JWT before setting these claims.
CREATE OR REPLACE FUNCTION private.current_user_id()
RETURNS UUID
LANGUAGE SQL
STABLE
SET search_path = ''
AS $$
    SELECT COALESCE(
        NULLIF(
            current_setting('request.jwt.claim.sub', true), ''
        ),
        (
            NULLIF(
                current_setting('request.jwt.claims', true), ''
            )::jsonb ->> 'sub'
        )
    )::uuid;
$$;

ALTER FUNCTION private.current_user_id() OWNER TO postgres;

-- 4. Membership helper functions.
CREATE OR REPLACE FUNCTION private.is_org_member(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.organization_members AS m
        WHERE m.organization_id = p_org_id
          AND m.user_id = private.current_user_id()
    );
$$;

CREATE OR REPLACE FUNCTION private.has_org_role(
    p_org_id UUID,
    p_roles TEXT[]
)
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.organization_members AS m
        WHERE m.organization_id = p_org_id
          AND m.user_id = private.current_user_id()
          AND m.role = ANY(p_roles)
    );
$$;

ALTER FUNCTION private.is_org_member(UUID) OWNER TO postgres;
ALTER FUNCTION private.has_org_role(UUID, TEXT[]) OWNER TO postgres;

-- 5. Secure organization creation.
-- The first member becomes the owner.
CREATE OR REPLACE FUNCTION private.create_organization(p_name TEXT)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_user_id UUID;
    v_org_id UUID;
BEGIN
    v_user_id := private.current_user_id();

    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Authenticated user required';
    END IF;

    IF p_name IS NULL OR length(trim(p_name)) = 0 THEN
        RAISE EXCEPTION 'Organization name is required';
    END IF;

    INSERT INTO public.organizations (name)
    VALUES (trim(p_name))
    RETURNING id INTO v_org_id;

    INSERT INTO public.organization_members (
        organization_id, user_id, role
    )
    VALUES (v_org_id, v_user_id, 'owner');

    RETURN v_org_id;
END;
$$;

ALTER FUNCTION private.create_organization(TEXT) OWNER TO postgres;

-- 6. Restrict function execution.
REVOKE ALL ON FUNCTION private.current_user_id()
    FROM PUBLIC, anon, authenticated;

REVOKE ALL ON FUNCTION private.is_org_member(UUID)
    FROM PUBLIC, anon, authenticated;

REVOKE ALL ON FUNCTION private.has_org_role(UUID, TEXT[])
    FROM PUBLIC, anon, authenticated;

REVOKE ALL ON FUNCTION private.create_organization(TEXT)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION private.current_user_id()
    TO forgettrace_app;

GRANT EXECUTE ON FUNCTION private.is_org_member(UUID)
    TO forgettrace_app;

GRANT EXECUTE ON FUNCTION private.has_org_role(UUID, TEXT[])
    TO forgettrace_app;

GRANT EXECUTE ON FUNCTION private.create_organization(TEXT)
    TO forgettrace_app;

-- 7. Remove direct access from browser-facing roles.
REVOKE ALL ON TABLE
    public.organizations,
    public.organization_members,
    public.data_sources,
    public.datasets,
    public.lineage_edges,
    public.scan_runs,
    public.subject_matches,
    public.audit_events
FROM PUBLIC, anon, authenticated;

-- 8. Grant minimum application privileges.
GRANT SELECT, UPDATE
    ON public.organizations TO forgettrace_app;

GRANT SELECT
    ON public.organization_members TO forgettrace_app;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON public.data_sources,
       public.datasets
TO forgettrace_app;

GRANT SELECT, INSERT, DELETE
    ON public.lineage_edges TO forgettrace_app;

GRANT SELECT, INSERT, UPDATE
    ON public.scan_runs,
       public.subject_matches
TO forgettrace_app;

GRANT SELECT, INSERT
    ON public.audit_events TO forgettrace_app;

-- 9. Enable and force RLS.
ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organizations FORCE ROW LEVEL SECURITY;

ALTER TABLE public.organization_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_members FORCE ROW LEVEL SECURITY;

ALTER TABLE public.data_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_sources FORCE ROW LEVEL SECURITY;

ALTER TABLE public.datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.datasets FORCE ROW LEVEL SECURITY;

ALTER TABLE public.lineage_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lineage_edges FORCE ROW LEVEL SECURITY;

ALTER TABLE public.scan_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scan_runs FORCE ROW LEVEL SECURITY;

ALTER TABLE public.subject_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subject_matches FORCE ROW LEVEL SECURITY;

ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_events FORCE ROW LEVEL SECURITY;

-- 10. Remove policies if this migration is being retried.
DROP POLICY IF EXISTS organizations_select ON public.organizations;
DROP POLICY IF EXISTS organizations_update ON public.organizations;
DROP POLICY IF EXISTS members_select ON public.organization_members;
DROP POLICY IF EXISTS sources_select ON public.data_sources;
DROP POLICY IF EXISTS sources_insert ON public.data_sources;
DROP POLICY IF EXISTS sources_update ON public.data_sources;
DROP POLICY IF EXISTS sources_delete ON public.data_sources;
DROP POLICY IF EXISTS datasets_select ON public.datasets;
DROP POLICY IF EXISTS datasets_insert ON public.datasets;
DROP POLICY IF EXISTS datasets_update ON public.datasets;
DROP POLICY IF EXISTS datasets_delete ON public.datasets;
DROP POLICY IF EXISTS lineage_select ON public.lineage_edges;
DROP POLICY IF EXISTS lineage_insert ON public.lineage_edges;
DROP POLICY IF EXISTS lineage_delete ON public.lineage_edges;
DROP POLICY IF EXISTS scans_select ON public.scan_runs;
DROP POLICY IF EXISTS scans_insert ON public.scan_runs;
DROP POLICY IF EXISTS scans_update ON public.scan_runs;
DROP POLICY IF EXISTS matches_select ON public.subject_matches;
DROP POLICY IF EXISTS matches_insert ON public.subject_matches;
DROP POLICY IF EXISTS matches_update ON public.subject_matches;
DROP POLICY IF EXISTS audit_select ON public.audit_events;
DROP POLICY IF EXISTS audit_insert ON public.audit_events;

-- 11. Organizations.
CREATE POLICY organizations_select
ON public.organizations
FOR SELECT TO forgettrace_app
USING ((SELECT private.is_org_member(id)));

CREATE POLICY organizations_update
ON public.organizations
FOR UPDATE TO forgettrace_app
USING ((SELECT private.has_org_role(id, ARRAY['owner', 'admin'])))
WITH CHECK ((SELECT private.has_org_role(id, ARRAY['owner', 'admin'])));

-- 12. Memberships: read-only through ordinary application queries.
CREATE POLICY members_select
ON public.organization_members
FOR SELECT TO forgettrace_app
USING ((SELECT private.is_org_member(organization_id)));

-- 13. Data sources.
CREATE POLICY sources_select
ON public.data_sources
FOR SELECT TO forgettrace_app
USING ((SELECT private.is_org_member(organization_id)));

CREATE POLICY sources_insert
ON public.data_sources
FOR INSERT TO forgettrace_app
WITH CHECK ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin']
)));

CREATE POLICY sources_update
ON public.data_sources
FOR UPDATE TO forgettrace_app
USING ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin']
)))
WITH CHECK ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin']
)));

CREATE POLICY sources_delete
ON public.data_sources
FOR DELETE TO forgettrace_app
USING ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin']
)));

-- 14. Datasets.
CREATE POLICY datasets_select
ON public.datasets
FOR SELECT TO forgettrace_app
USING ((SELECT private.is_org_member(organization_id)));

CREATE POLICY datasets_insert
ON public.datasets
FOR INSERT TO forgettrace_app
WITH CHECK ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin', 'analyst']
)));

CREATE POLICY datasets_update
ON public.datasets
FOR UPDATE TO forgettrace_app
USING ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin', 'analyst']
)))
WITH CHECK ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin', 'analyst']
)));

CREATE POLICY datasets_delete
ON public.datasets
FOR DELETE TO forgettrace_app
USING ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin']
)));

-- 15. Lineage.
CREATE POLICY lineage_select
ON public.lineage_edges
FOR SELECT TO forgettrace_app
USING ((SELECT private.is_org_member(organization_id)));

CREATE POLICY lineage_insert
ON public.lineage_edges
FOR INSERT TO forgettrace_app
WITH CHECK ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin', 'analyst']
)));

CREATE POLICY lineage_delete
ON public.lineage_edges
FOR DELETE TO forgettrace_app
USING ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin']
)));

-- 16. Scan runs.
CREATE POLICY scans_select
ON public.scan_runs
FOR SELECT TO forgettrace_app
USING ((SELECT private.is_org_member(organization_id)));

CREATE POLICY scans_insert
ON public.scan_runs
FOR INSERT TO forgettrace_app
WITH CHECK ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin', 'analyst']
)));

CREATE POLICY scans_update
ON public.scan_runs
FOR UPDATE TO forgettrace_app
USING ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin', 'analyst']
)))
WITH CHECK ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin', 'analyst']
)));

-- 17. Subject matches.
CREATE POLICY matches_select
ON public.subject_matches
FOR SELECT TO forgettrace_app
USING ((SELECT private.is_org_member(organization_id)));

CREATE POLICY matches_insert
ON public.subject_matches
FOR INSERT TO forgettrace_app
WITH CHECK ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin', 'analyst']
)));

CREATE POLICY matches_update
ON public.subject_matches
FOR UPDATE TO forgettrace_app
USING ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin', 'analyst']
)))
WITH CHECK ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin', 'analyst']
)));

-- 18. Audit events: append-only.
CREATE POLICY audit_select
ON public.audit_events
FOR SELECT TO forgettrace_app
USING ((SELECT private.has_org_role(
    organization_id, ARRAY['owner', 'admin']
)));

CREATE POLICY audit_insert
ON public.audit_events
FOR INSERT TO forgettrace_app
WITH CHECK (
    actor_user_id = (SELECT private.current_user_id())
    AND (SELECT private.is_org_member(organization_id))
);

COMMIT;
