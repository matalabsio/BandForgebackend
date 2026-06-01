-- BandForge Reading Task 3
-- mock_test_id = b0000000-0000-4000-8000-000000000003

DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000003'
);
DELETE FROM module_scores WHERE attempt_id IN (
  SELECT id FROM test_attempts WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000003'
);
DELETE FROM test_attempts WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000003';
DELETE FROM questions WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000003';

INSERT INTO mock_tests (id, title, description, is_published)
VALUES (
  'b0000000-0000-4000-8000-000000000003',
  'When the Rainforests of the Sea Fall Silent',
  'Academic Reading — coral reefs and climate threats (TFNG, matching headings, sentence completion).',
  true
)
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  is_published = true;

INSERT INTO questions (
  mock_test_id, module, question_type, question_number, prompt,
  passage_text, options, correct_answer, skill_tag
) VALUES
('b0000000-0000-4000-8000-000000000003', 'reading', 'tfng', 1, 'Coral reefs cover more than ten per cent of the ocean floor.', 'When the Rainforests of the Sea Fall Silent

A    Coral reefs occupy a curious place in the natural world. Although they cover less than one per cent of the ocean floor, they provide a home for roughly a quarter of all marine species, an extraordinary concentration of life that has earned them the nickname "rainforests of the sea". Few environments on Earth pack so much biological diversity into so small an area. This abundance is not accidental. Reefs are built over thousands of years by tiny animals called polyps, which secrete limestone skeletons that accumulate into vast and complex structures. The result is a habitat of remarkable intricacy, offering shelter, breeding grounds and feeding opportunities to creatures ranging from microscopic plankton to large predatory fish.

B    The vitality of reefs depends on an unusual partnership. Coral polyps share their tissues with single-celled algae known as zooxanthellae, which use sunlight to produce energy through photosynthesis and supply most of the coral''s food. In return, the polyps provide the algae with shelter and nutrients. The algae also give corals their brilliant colours. This relationship is delicate, however. When water temperatures rise even slightly above the normal seasonal maximum, the polyps expel their algae in a harmful process known as bleaching. Stripped of their symbionts, corals turn white. They are not yet dead, but they are starving, and if conditions do not improve quickly they will not survive.

C    The scale of recent bleaching events has alarmed scientists. In 2016, an exceptionally warm year, large sections of Australia''s Great Barrier Reef were affected. A widely cited study led by Terry Hughes of the ARC Centre of Excellence for Coral Reef Studies found that around two-thirds of corals in the worst-affected northern stretch died within months. What disturbed researchers as much as the damage itself was its frequency: where bleaching events once had decades between them, they can now strike again within a few years, leaving little time for recovery.

D    Warming is not the only threat. As the atmosphere absorbs substantial quantities of carbon dioxide released by human activity, the gas dissolves into the ocean and makes seawater more acidic. This shift in chemistry makes it harder for corals and other organisms to build and maintain limestone skeletons, slowing growth and weakening existing structures. Ocean acidification works quietly, but it undermines the physical foundation on which entire reef ecosystems depend.

E    Climate pressures combine with more local stresses. Overfishing removes species that graze on algae and keep reefs clear; agricultural runoff carries fertilisers and sediment that smother corals; coastal development, dredging and pollution add further damage. Together, these factors reduce a reef''s resilience, leaving it less able to recover from bleaching or storms.

F    The consequences of reef decline extend far beyond the water. Reefs act as natural breakwaters that protect coastlines from waves and storms, and they support fishing and tourism industries worth billions of dollars annually. Approximately half a billion people worldwide depend on reefs for food or income. When reefs degrade, communities lose resources they cannot easily replace.

G    The outlook is sobering. The Intergovernmental Panel on Climate Change has projected that even if global warming is held to 1.5 degrees Celsius, between seventy and ninety per cent of the world''s coral reefs could disappear; at two degrees, virtually all may be lost. Some scientists argue that only rapid cuts in greenhouse-gas emissions, combined with local protection, offer a realistic chance of preserving reefs within the present century.', '[{"label": "TRUE", "text": "TRUE"}, {"label": "FALSE", "text": "FALSE"}, {"label": "NOT GIVEN", "text": "NOT GIVEN"}]'::jsonb, 'FALSE', 'tfng'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'tfng', 2, 'Zooxanthellae provide corals with most of their food through photosynthesis.', NULL, '[{"label": "TRUE", "text": "TRUE"}, {"label": "FALSE", "text": "FALSE"}, {"label": "NOT GIVEN", "text": "NOT GIVEN"}]'::jsonb, 'TRUE', 'tfng'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'tfng', 3, 'Bleached corals are immediately dead once they turn white.', NULL, '[{"label": "TRUE", "text": "TRUE"}, {"label": "FALSE", "text": "FALSE"}, {"label": "NOT GIVEN", "text": "NOT GIVEN"}]'::jsonb, 'FALSE', 'tfng'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'tfng', 4, 'Hughes''s study found that two-thirds of corals died in the southern section of the Great Barrier Reef in 2016.', NULL, '[{"label": "TRUE", "text": "TRUE"}, {"label": "FALSE", "text": "FALSE"}, {"label": "NOT GIVEN", "text": "NOT GIVEN"}]'::jsonb, 'FALSE', 'tfng'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'tfng', 5, 'Ocean acidification makes it easier for corals to build limestone skeletons.', NULL, '[{"label": "TRUE", "text": "TRUE"}, {"label": "FALSE", "text": "FALSE"}, {"label": "NOT GIVEN", "text": "NOT GIVEN"}]'::jsonb, 'FALSE', 'tfng'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'matching_headings', 6, 'Paragraph B', NULL, '[{"label": "i", "text": "How reefs support a disproportionate share of marine life"}, {"label": "ii", "text": "The symbiotic relationship that gives reefs their colour"}, {"label": "iii", "text": "Evidence that bleaching events are becoming more frequent"}, {"label": "iv", "text": "How carbon emissions weaken coral skeletons"}, {"label": "v", "text": "Human activities that damage reefs at a local level"}, {"label": "vi", "text": "Economic and social costs when reefs decline"}, {"label": "vii", "text": "Projections for reef survival under climate scenarios"}]'::jsonb, 'ii', 'matching_headings'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'matching_headings', 7, 'Paragraph C', NULL, '[{"label": "i", "text": "How reefs support a disproportionate share of marine life"}, {"label": "ii", "text": "The symbiotic relationship that gives reefs their colour"}, {"label": "iii", "text": "Evidence that bleaching events are becoming more frequent"}, {"label": "iv", "text": "How carbon emissions weaken coral skeletons"}, {"label": "v", "text": "Human activities that damage reefs at a local level"}, {"label": "vi", "text": "Economic and social costs when reefs decline"}, {"label": "vii", "text": "Projections for reef survival under climate scenarios"}]'::jsonb, 'iii', 'matching_headings'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'matching_headings', 8, 'Paragraph D', NULL, '[{"label": "i", "text": "How reefs support a disproportionate share of marine life"}, {"label": "ii", "text": "The symbiotic relationship that gives reefs their colour"}, {"label": "iii", "text": "Evidence that bleaching events are becoming more frequent"}, {"label": "iv", "text": "How carbon emissions weaken coral skeletons"}, {"label": "v", "text": "Human activities that damage reefs at a local level"}, {"label": "vi", "text": "Economic and social costs when reefs decline"}, {"label": "vii", "text": "Projections for reef survival under climate scenarios"}]'::jsonb, 'iv', 'matching_headings'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'matching_headings', 9, 'Paragraph E', NULL, '[{"label": "i", "text": "How reefs support a disproportionate share of marine life"}, {"label": "ii", "text": "The symbiotic relationship that gives reefs their colour"}, {"label": "iii", "text": "Evidence that bleaching events are becoming more frequent"}, {"label": "iv", "text": "How carbon emissions weaken coral skeletons"}, {"label": "v", "text": "Human activities that damage reefs at a local level"}, {"label": "vi", "text": "Economic and social costs when reefs decline"}, {"label": "vii", "text": "Projections for reef survival under climate scenarios"}]'::jsonb, 'v', 'matching_headings'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'sentence_completion', 10, 'Reefs are constructed by small animals called ______.', NULL, NULL, 'polyps', 'sentence_completion'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'sentence_completion', 11, 'When corals expel their algae, the process is known as ______.', NULL, NULL, 'bleaching', 'sentence_completion'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'sentence_completion', 12, 'Dissolved carbon dioxide makes seawater more ______.', NULL, NULL, 'acidic', 'sentence_completion'),
('b0000000-0000-4000-8000-000000000003', 'reading', 'sentence_completion', 13, 'The IPCC warns that holding warming to 1.5°C may still leave up to ______ per cent of reefs gone.', NULL, NULL, 'ninety/90', 'sentence_completion');
