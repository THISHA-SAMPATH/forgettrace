
-- ForgetTrace: Backend-only Row Level Security
-- Migration 002
-- Requires Migration 001 and Supabase Auth.

BEGIN;

-- 1. Dedicated non-login application role.
CREATE ROLE forgettrace_app
    NOLOGIN
    NOINHERIT
    NOBYPASSRLS;

-- 2. Private schema.
CREATE SCHEMA IF NOT EXISTS private;

REVOKE ALL ON SCHEMA private FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA private TO forgettrace_app;

-- 3. Secure current-user helper.
-- The function runs as its owner and reads the verified Supabase JWT context.
CREATE OR REPLACE FUNCTION private.current_user_id()
RETURNS UUID
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT auth.uid();
$$;

REVOKE ALL ON FUNCTION private.current_user_id()
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION private.current_user_id()
    TO forgettrace_app;

-- 4. Organisation membership helpers.
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
          AND m.user_id = (SELECT private.current_user_id())
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
          AND m.user_id = (SELECT private.current_user_id())
          AND m.role = ANY(p_roles)
    );
$$;

REVOKE ALL ON FUNCTION private.is_org_member(UUID)
    FROM PUBLIC, anon, authenticated;

REVOKE ALL ON FUNCTION private.has_org_role(UUID, TEXT[])
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION private.is_org_member(UUID)
    TO forgettrace_app;

GRANT EXECUTE ON FUNCTION private.has_org_role(UUID, TEXT[])
    TO forgettrace_app;

-- 5. Remove direct access through ordinary Supabase API roles.
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

GRANT USAGE ON SCHEMA public TO forgettrace_app;

-- 6. Least-privilege table permissions.

GRANT SELECT ON public.organizations TO forgettrace_app;
GRANT UPDATE (name) ON public.organizations TO forgettrace_app;

GRANT SELECT ON public.organization_members TO forgettrace_app;

GRANT SELECT, INSERT, DELETE ON public.data_sources TO forgettrace_app;
GRANT UPDATE (name, secret_ref, configuration, status)
    ON public.data_sources TO forgettrace_app;

GRANT SELECT, INSERT, DELETE ON public.datasets TO forgettrace_app;
GRANT UPDATE (subject_columns, metadata)
    ON public.datasets TO forgettrace_app;

GRANT SELECT, INSERT, DELETE ON public.lineage_edges TO forgettrace_app;

GRANT SELECT, INSERT, DELETE ON public.scan_runs TO forgettrace_app;
GRANT UPDATE (status, started_at, finished_at, summary, error_code)
    ON public.scan_runs TO forgettrace_app;

GRANT SELECT, INSERT ON public.subject_matches TO forgettrace_app;

GRANT SELECT ON public.audit_events TO forgettrace_app;

-- 7. Controlled organisation creation.
CREATE OR REPLACE FUNCTION private.create_organization(p_name TEXT)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_org_id UUID;
    v_user_id UUID;
BEGIN
    v_user_id := private.current_user_id();

    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Authentication required';
    END IF;

    IF p_name IS NULL
       OR length(trim(p_name)) = 0
       OR length(trim(p_name)) > 120 THEN
        RAISE EXCEPTION 'Organization name must contain 1 to 120 characters';
    END IF;

    INSERT INTO public.organizations (name)
    VALUES (trim(p_name))
    RETURNING id INTO v_org_id;

    INSERT INTO public.organization_members (
        organization_id,
        user_id,
        role
    )
    VALUES (v_org_id, v_user_id, 'owner');

    RETURN v_org_id;
END;
$$;

REVOKE ALL ON FUNCTION private.create_organization(TEXT)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION private.create_organization(TEXT)
    TO forgettrace_app;

-- 8. Controlled, append-only audit event creation.
CREATE OR REPLACE FUNCTION private.append_audit_event(
    p_org_id UUID,
    p_event_type TEXT,
    p_target_type TEXT DEFAULT NULL,
    p_target_id UUID DEFAULT NULL,
    p_details JSONB DEFAULT '{}'::JSONB
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_actor UUID;
    v_event_id UUID;
BEGIN
    v_actor := private.current_user_id();

    IF v_actor IS NULL THEN
        RAISE EXCEPTION 'Authentication required';
    END IF;

    IF NOT private.is_org_member(p_org_id) THEN
        RAISE EXCEPTION 'Not an organization member';
    END IF;

    IF p_event_type IS NULL
       OR length(trim(p_event_type)) = 0
       OR length(trim(p_event_type)) > 100 THEN
        RAISE EXCEPTION 'Invalid event type';
    END IF;

    IF p_target_type IS NOT NULL
       AND length(p_target_type) > 100 THEN
        RAISE EXCEPTION 'Invalid target type';
    END IF;

    INSERT INTO public.audit_events (
        organization_id,
        actor_user_id,
        event_type,
        target_type,
        target_id,
        details
    )
    VALUES (
        p_org_id,
        v_actor,
        trim(p_event_type),
        p_target_type,
        p_target_id,
        COALESCE(p_details, '{}'::JSONB)
    )
    RETURNING id INTO v_event_id;

    RETURN v_event_id;
END;
$$;

REVOKE ALL ON FUNCTION private.append_audit_event(
    UUID, TEXT, TEXT, UUID, JSONB
) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION private.append_audit_event(
    UUID, TEXT, TEXT, UUID, JSONB
) TO forgettrace_app;

-- 9. Force RLS on all eight application tables.
ALTER TABLE public.organizations FORCE ROW LEVEL SECURITY;
ALTER TABLE public.organization_members FORCE ROW LEVEL SECURITY;
ALTER TABLE public.data_sources FORCE ROW LEVEL SECURITY;
ALTER TABLE public.datasets FORCE ROW LEVEL SECURITY;
ALTER TABLE public.lineage_edges FORCE ROW LEVEL SECURITY;
ALTER TABLE public.scan_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE public.subject_matches FORCE ROW LEVEL SECURITY;
ALTER TABLE public.audit_events FORCE ROW LEVEL SECURITY;

-- 10. Organizations.
CREATE POLICY organizations_select
ON public.organizations
FOR SELECT TO forgettrace_app
USING (private.is_org_member(id));

CREATE POLICY organizations_update
ON public.organizations
FOR UPDATE TO forgettrace_app
USING (private.has_org_role(id, ARRAY['owner', 'admin']))
WITH CHECK (private.has_org_role(id, ARRAY['owner', 'admin']));

-- No ordinary organization DELETE permission or policy.
-- This protects related audit history from cascading deletion.

-- 11. Organization members.
CREATE POLICY members_select
ON public.organization_members
FOR SELECT TO forgettrace_app
USING (private.is_org_member(organization_id));

-- Membership changes are intentionally not granted yet.
-- Controlled invitation and role-management functions will be added later.

-- 12. Data sources.
CREATE POLICY sources_select
ON public.data_sources
FOR SELECT TO forgettrace_app
USING (private.is_org_member(organization_id));

CREATE POLICY sources_insert
ON public.data_sources
FOR INSERT TO forgettrace_app
WITH CHECK (
    private.has_org_role(organization_id, ARRAY['owner', 'admin'])
);

CREATE POLICY sources_update
ON public.data_sources
FOR UPDATE TO forgettrace_app
USING (
    private.has_org_role(organization_id, ARRAY['owner', 'admin'])
)
WITH CHECK (
    private.has_org_role(organization_id, ARRAY['owner', 'admin'])
);

CREATE POLICY sources_delete
ON public.data_sources
FOR DELETE TO forgettrace_app
USING (
    private.has_org_role(organization_id, ARRAY['owner', 'admin'])
);

-- 13. Datasets.
CREATE POLICY datasets_select
ON public.datasets
FOR SELECT TO forgettrace_app
USING (private.is_org_member(organization_id));

CREATE POLICY datasets_insert
ON public.datasets
FOR INSERT TO forgettrace_app
WITH CHECK (
    private.has_org_role(
        organization_id,
        ARRAY['owner', 'admin', 'analyst']
    )
);

CREATE POLICY datasets_update
ON public.datasets
FOR UPDATE TO forgettrace_app
USING (
    private.has_org_role(
        organization_id,
        ARRAY['owner', 'admin', 'analyst']
    )
)
WITH CHECK (
    private.has_org_role(
        organization_id,
        ARRAY['owner', 'admin', 'analyst']
    )
);

CREATE POLICY datasets_delete
ON public.datasets
FOR DELETE TO forgettrace_app
USING (
    private.has_org_role(organization_id, ARRAY['owner', 'admin'])
);

-- 14. Lineage edges.
CREATE POLICY lineage_select
ON public.lineage_edges
FOR SELECT TO forgettrace_app
USING (private.is_org_member(organization_id));

CREATE POLICY lineage_insert
ON public.lineage_edges
FOR INSERT TO forgettrace_app
WITH CHECK (
    private.has_org_role(
        organization_id,
        ARRAY['owner', 'admin', 'analyst']
    )
);

CREATE POLICY lineage_delete
ON public.lineage_edges
FOR DELETE TO forgettrace_app
USING (
    private.has_org_role(organization_id, ARRAY['owner', 'admin'])
);

-- 15. Scan runs.
CREATE POLICY scans_select
ON public.scan_runs
FOR SELECT TO forgettrace_app
USING (private.is_org_member(organization_id));

CREATE POLICY scans_insert
ON public.scan_runs
FOR INSERT TO forgettrace_app
WITH CHECK (
    private.has_org_role(
        organization_id,
        ARRAY['owner', 'admin', 'analyst']
    )
);

CREATE POLICY scans_update
ON public.scan_runs
FOR UPDATE TO forgettrace_app
USING (
    private.has_org_role(
        organization_id,
        ARRAY['owner', 'admin', 'analyst']
    )
)
WITH CHECK (
    private.has_org_role(
        organization_id,
        ARRAY['owner', 'admin', 'analyst']
    )
);

CREATE POLICY scans_delete
ON public.scan_runs
FOR DELETE TO forgettrace_app
USING (
    private.has_org_role(organization_id, ARRAY['owner', 'admin'])
);

-- 16. Subject matches are immutable after insertion.
CREATE POLICY matches_select
ON public.subject_matches
FOR SELECT TO forgettrace_app
USING (private.is_org_member(organization_id));

CREATE POLICY matches_insert
ON public.subject_matches
FOR INSERT TO forgettrace_app
WITH CHECK (
    private.has_org_role(
        organization_id,
        ARRAY['owner', 'admin', 'analyst']
    )
);

-- 17. Audit events are readable only by owners and admins.
-- Inserts are performed through private.append_audit_event().
CREATE POLICY audit_select
ON public.audit_events
FOR SELECT TO forgettrace_app
USING (
    private.has_org_role(organization_id, ARRAY['owner', 'admin'])
);

COMMIT;
