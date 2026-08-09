-- Lock payment/score/mock SECURITY DEFINER RPCs to service_role only.
-- App calls these via FastAPI service role; anon must not invoke via PostgREST.

REVOKE ALL ON FUNCTION public.confirm_payment_paid_bundle(text, text, text, timestamptz, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.persist_module_submit_bundle(uuid, uuid, timestamptz, jsonb, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.get_mock_start_context(uuid, uuid, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.get_mock_start_gate_context(uuid, uuid, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.get_mock_attempt_progress(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.abandon_mock_attempt_session(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.abandon_mock_attempt_children(uuid) FROM PUBLIC;

REVOKE EXECUTE ON FUNCTION public.confirm_payment_paid_bundle(text, text, text, timestamptz, timestamptz) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.persist_module_submit_bundle(uuid, uuid, timestamptz, jsonb, text, jsonb) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.get_mock_start_context(uuid, uuid, boolean) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.get_mock_start_gate_context(uuid, uuid, boolean) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.get_mock_attempt_progress(uuid, uuid) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.abandon_mock_attempt_session(uuid) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.abandon_mock_attempt_children(uuid) FROM anon, authenticated;

GRANT EXECUTE ON FUNCTION public.confirm_payment_paid_bundle(text, text, text, timestamptz, timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.persist_module_submit_bundle(uuid, uuid, timestamptz, jsonb, text, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_mock_start_context(uuid, uuid, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_mock_start_gate_context(uuid, uuid, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_mock_attempt_progress(uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.abandon_mock_attempt_session(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.abandon_mock_attempt_children(uuid) TO service_role;
