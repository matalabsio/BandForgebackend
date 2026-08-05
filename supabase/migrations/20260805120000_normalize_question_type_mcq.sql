-- Phase 3: normalize MCQ type slugs to canonical `mcq`
UPDATE questions
SET question_type = 'mcq'
WHERE lower(question_type) IN ('multiple_choice', 'multiple-choice');

UPDATE bank_questions
SET question_type = 'mcq'
WHERE lower(question_type) IN ('multiple_choice', 'multiple-choice');
