-- Unpublish legacy Deferral reading mock (replaced by founder Tasks 2 & 3)
UPDATE mock_tests SET is_published = false WHERE id = 'b0000000-0000-4000-8000-000000000001';
