-- Historical price migration for full_skill_program (299900 paise = Rs. 2999).
-- Superseded by 20260824110000_full_skill_program_price_2499.sql.
-- Phase 0 seed used placeholder amount=100; ON CONFLICT did not update amount.

UPDATE plans
SET amount = 299900,
    duration_days = 365,
    description = 'All L/R/W/S practice hubs + personalised plan until your exam date.'
WHERE slug = 'full_skill_program';
