-- IELTS Reading mock seed from ielts.md
-- Run after base migrations. Safe to re-run for this mock_test_id.

-- 1) Choose / keep a stable mock test ID
--    You can replace this UUID if needed, but keep it consistent across deletes/inserts below.
--    mock_test_id = b0000000-0000-4000-8000-000000000001

DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000001'
);
DELETE FROM questions WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000001';
DELETE FROM test_attempts WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000001';

INSERT INTO mock_tests (id, title, description, is_published)
VALUES (
  'b0000000-0000-4000-8000-000000000001',
  'IELTS Reading — Deferral Dilemma (Band 6.5–7.0)',
  '13-question reading mock from ielts.md (TFNG, matching headings, sentence completion).',
  true
)
ON CONFLICT (id) DO UPDATE
SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  is_published = true;

-- Shared passage (paragraphs A-G)
INSERT INTO questions (
  mock_test_id, module, question_type, question_number, prompt,
  passage_text, options, correct_answer, skill_tag
) VALUES
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 1,
  'Piers Steel''s 2007 meta-analysis found that approximately 15 to 20 percent of the adult general population are chronic procrastinators.',
  'The Deferral Dilemma: Understanding Procrastination in Academic Contexts
A    Few behavioural patterns are as widely recognised yet poorly understood as procrastination. Broadly defined as the voluntary delay of an intended course of action despite expecting to be worse off for the delay, procrastination is not simply a matter of poor time management. Research conducted over the past three decades has consistently positioned it as an emotional regulation failure — a short-term strategy for avoiding the discomfort associated with a task, regardless of the long-term consequences. According to a comprehensive meta-analysis conducted by Piers Steel of the University of Calgary in 2007, approximately 15 to 20 percent of the general adult population identify as chronic procrastinators, a figure that rises dramatically among student populations.
B    In academic settings, the prevalence of procrastination is particularly striking. Studies have estimated that between 80 and 95 percent of college students engage in procrastination to some degree, with around 50 percent doing so consistently and problematically. These students frequently delay beginning essays, revising for examinations, or completing assigned readings, often until the pressure of an imminent deadline becomes unbearable. The consequences are not merely academic: students who procrastinate habitually report higher levels of stress, increased feelings of guilt, and diminished overall wellbeing compared with their more punctual peers. What is especially significant is that these students are rarely unaware of their behaviour; most acknowledge the pattern and express a genuine desire to change it.
C    The psychological mechanisms underlying procrastination are complex and interconnected. Central to current theoretical models is the concept of task aversion — the degree to which a person finds a given activity unpleasant, boring, frustrating, or anxiety-inducing. When a task triggers negative emotions, the brain''s impulse control systems are placed in direct competition with its reward-seeking circuits. Procrastination, in this context, represents a temporary victory for the latter: by abandoning the unpleasant task in favour of a more immediately gratifying activity, the individual experiences a short-term reduction in emotional distress. Timothy Pychyl, a psychologist at Carleton University in Ottawa, has described this dynamic as a form of "give in to feel good," emphasising that the relief procrastination affords is genuine, if fleeting.
D    The academic performance costs of habitual procrastination are well documented. Students who regularly defer their work tend to produce lower-quality output, submit assignments later — sometimes incurring grade penalties — and perform worse in examinations than students with comparable ability who manage their time effectively. A longitudinal study tracking undergraduate students over a full academic year found that procrastination at the start of term was a significant predictor of final course grades, even after controlling for intelligence and prior academic achievement. Crucially, procrastinators did not compensate for their delayed start by working more intensively once they did begin; they simply had less time and, consequently, achieved less.
E    One of the more counterintuitive findings in procrastination research concerns the role of self-criticism. Many people assume that holding themselves to rigorous internal standards and feeling guilty about procrastinating will motivate corrective behaviour. However, research by Fuschia Sirois of the University of Sheffield has demonstrated that high levels of self-blame are more likely to perpetuate procrastination than to reduce it. When students respond to an episode of procrastination with harsh self-judgment, they experience heightened emotional distress, which in turn increases the likelihood of further avoidance. By contrast, students who approached their own procrastination with self-compassion — acknowledging the behaviour without excessive self-recrimination — were more likely to re-engage with their tasks promptly.
F    Interventions aimed at reducing academic procrastination have yielded mixed but instructive results. Strategies focusing purely on time management skills, such as calendar use and goal-setting workshops, have shown limited effectiveness when applied in isolation, suggesting that procrastination cannot be addressed solely through organisational tools. More promising outcomes have been reported for approaches that target the emotional dimensions of the problem — specifically, techniques drawn from cognitive behavioural therapy that help students identify and challenge distorted beliefs about tasks, such as catastrophising about failure or holding unrealistic perfectionist standards. Brief mindfulness-based interventions have also shown potential, as they appear to increase students'' tolerance of the discomfort that task initiation can produce.
G    The study of procrastination has broader implications beyond the university setting. As societies increasingly demand self-directed work and autonomous learning, the capacity to regulate one''s own behaviour in the face of unappealing tasks becomes a critical competency. Educators and institutional designers may benefit from understanding that a student who procrastinates is not necessarily lazy or indifferent, but may instead be struggling with emotional self-regulation in a way that is amenable to targeted support. Reframing procrastination as a psychological challenge rather than a moral failing represents a shift in perspective that could meaningfully improve outcomes for students who currently suffer its academic and personal consequences in silence.',
  NULL,
  'TRUE',
  'tfng'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 2,
  'Most students who procrastinate are unaware of their own behaviour and have no wish to change it.',
  NULL,
  NULL,
  'FALSE',
  'tfng'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 3,
  'Piers Steel''s meta-analysis was published in a peer-reviewed psychology journal.',
  NULL,
  NULL,
  'NOT GIVEN',
  'tfng'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 4,
  'The longitudinal study described in the passage took into account both the intelligence and the prior academic achievement of the students observed.',
  NULL,
  NULL,
  'TRUE',
  'tfng'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'tfng', 5,
  'According to Fuschia Sirois, students who blame themselves harshly for procrastinating are more likely to stop the behaviour than those who do not.',
  NULL,
  NULL,
  'FALSE',
  'tfng'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'matching_headings', 6,
  'Paragraph C',
  NULL,
  '[{"label":"i","text":"The physical health consequences of chronic delay"},{"label":"ii","text":"How emotional avoidance sustains the cycle of delay"},{"label":"iii","text":"The long-term academic cost of habitual procrastination"},{"label":"iv","text":"Cultural differences in student attitudes to academic deadlines"},{"label":"v","text":"Why self-blame may worsen rather than resolve the problem"},{"label":"vi","text":"The connection between perfectionism and academic anxiety"},{"label":"vii","text":"Promising approaches to reducing procrastination in students"}]'::jsonb,
  'ii',
  'matching_headings'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'matching_headings', 7,
  'Paragraph D',
  NULL,
  '[{"label":"i","text":"The physical health consequences of chronic delay"},{"label":"ii","text":"How emotional avoidance sustains the cycle of delay"},{"label":"iii","text":"The long-term academic cost of habitual procrastination"},{"label":"iv","text":"Cultural differences in student attitudes to academic deadlines"},{"label":"v","text":"Why self-blame may worsen rather than resolve the problem"},{"label":"vi","text":"The connection between perfectionism and academic anxiety"},{"label":"vii","text":"Promising approaches to reducing procrastination in students"}]'::jsonb,
  'iii',
  'matching_headings'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'matching_headings', 8,
  'Paragraph E',
  NULL,
  '[{"label":"i","text":"The physical health consequences of chronic delay"},{"label":"ii","text":"How emotional avoidance sustains the cycle of delay"},{"label":"iii","text":"The long-term academic cost of habitual procrastination"},{"label":"iv","text":"Cultural differences in student attitudes to academic deadlines"},{"label":"v","text":"Why self-blame may worsen rather than resolve the problem"},{"label":"vi","text":"The connection between perfectionism and academic anxiety"},{"label":"vii","text":"Promising approaches to reducing procrastination in students"}]'::jsonb,
  'v',
  'matching_headings'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'matching_headings', 9,
  'Paragraph F',
  NULL,
  '[{"label":"i","text":"The physical health consequences of chronic delay"},{"label":"ii","text":"How emotional avoidance sustains the cycle of delay"},{"label":"iii","text":"The long-term academic cost of habitual procrastination"},{"label":"iv","text":"Cultural differences in student attitudes to academic deadlines"},{"label":"v","text":"Why self-blame may worsen rather than resolve the problem"},{"label":"vi","text":"The connection between perfectionism and academic anxiety"},{"label":"vii","text":"Promising approaches to reducing procrastination in students"}]'::jsonb,
  'vii',
  'matching_headings'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'sentence_completion', 10,
  'Researchers have increasingly characterised procrastination as a failure of ________________________ rather than simply an issue of poor organisation or planning.',
  NULL,
  NULL,
  'emotional regulation',
  'sentence_completion'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'sentence_completion', 11,
  'Timothy Pychyl described the mechanism of procrastination as a "give in to ________________________" dynamic, in which avoidance produces emotional relief that is genuine but short-lived.',
  NULL,
  NULL,
  'feel good',
  'sentence_completion'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'sentence_completion', 12,
  'Fuschia Sirois''s research found that students who responded to their procrastination with ________________________ were more likely to re-engage with their work without further delay.',
  NULL,
  NULL,
  'self-compassion',
  'sentence_completion'
),
(
  'b0000000-0000-4000-8000-000000000001', 'reading', 'sentence_completion', 13,
  'Strategies that focus solely on organisational skills such as calendar use and goal-setting workshops have demonstrated only ________________________ effectiveness when used as the primary intervention.',
  NULL,
  NULL,
  'limited',
  'sentence_completion'
);
