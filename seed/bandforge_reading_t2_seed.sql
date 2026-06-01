-- BandForge reading seed: The Hidden Forces Behind Everyday Choices
-- mock_test_id = b0000000-0000-4000-8000-000000000002

DELETE FROM answers WHERE question_id IN (
  SELECT id FROM questions WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000002'
);
DELETE FROM questions WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000002';
DELETE FROM test_attempts WHERE mock_test_id = 'b0000000-0000-4000-8000-000000000002';

INSERT INTO mock_tests (id, title, description, is_published)
VALUES (
  'b0000000-0000-4000-8000-000000000002',
  'The Hidden Forces Behind Everyday Choices',
  'Academic Reading — behavioural economics (TFNG, matching headings, sentence completion).',
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
('b0000000-0000-4000-8000-000000000002', 'reading', 'tfng', 1, 'Homo economicus provides an accurate description of how most people make everyday decisions.', 'The Hidden Forces Behind Everyday Choices

A    For much of the twentieth century, economic theory rested on a confident assumption: that people behave as rational agents, weighing costs and benefits with cool precision before arriving at the choice that best serves their interests. This figure, often called homo economicus, was a useful simplification for building mathematical models, but it bore little resemblance to the messy reality of human behaviour. From the late twentieth century, a field emerged to close that gap, drawing on psychology to explain why ordinary consumers so often act in ways conventional theory cannot predict.

B    The most influential challenge came from psychologists Daniel Kahneman and Amos Tversky, whose work in the 1970s and 1980s reshaped the discipline through prospect theory. Their research demonstrated that people do not evaluate gains and losses symmetrically. Instead, they feel the pain of losing a sum of money roughly twice as intensely as the pleasure of gaining the same amount—a phenomenon known as loss aversion. This helps explain puzzling patterns: investors who hold on to failing shares rather than accept a loss, or shoppers who respond far more strongly to a price increase than to an equivalent discount.

C    A second well-documented bias is anchoring—the tendency for an initial piece of information to exert a disproportionate influence on subsequent judgments. When a retailer displays a high "original" price beside a discounted offer, the first figure functions as an anchor, making the deal appear more generous than it might otherwise seem. Anchors need not be meaningful; even random numbers can shift people''s estimates of unrelated quantities. This means that contextual cues quietly determine what feels like a fair price.

D    Perhaps the most counterintuitive finding concerns the effect of abundant choice. Classical economics holds that more options make consumers better off, since unwanted alternatives may simply be ignored. Yet a celebrated study by Sheena Iyengar and Mark Lepper suggested otherwise. In a supermarket taste test, a display of twenty-four jam varieties attracted more interest than one with six, but sales at the larger display were only three per cent, compared with thirty per cent for the smaller set. Extensive choice, it seems, can overwhelm shoppers and discourage purchase.

E    Research also highlights the power of defaults—the options that apply when no active choice is made. Eric Johnson and Daniel Goldstein compared organ-donation systems across countries and found striking differences. Nations that use opt-out registration, in which citizens are donors unless they object, achieve participation rates above ninety per cent, whereas opt-in countries typically record less than twenty per cent. The default frames the decision and largely determines the outcome.

F    More recently, Richard Thaler and Cass Sunstein popularised the idea of the nudge—a small change in how choices are presented that steers behaviour without forbidding any option, such as placing fruit at eye level in a canteen. They describe this as libertarian paternalism. Governments and businesses worldwide have adopted nudge-based programmes, though critics argue that such techniques can be manipulative when the public lacks awareness of the design.', '[{"label": "TRUE", "text": "TRUE"}, {"label": "FALSE", "text": "FALSE"}, {"label": "NOT GIVEN", "text": "NOT GIVEN"}]'::jsonb, 'FALSE', 'tfng'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'tfng', 2, 'Kahneman and Tversky found that losses and gains of equal size are felt with equal intensity.', NULL, '[{"label": "TRUE", "text": "TRUE"}, {"label": "FALSE", "text": "FALSE"}, {"label": "NOT GIVEN", "text": "NOT GIVEN"}]'::jsonb, 'FALSE', 'tfng'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'tfng', 3, 'Anchoring effects only occur when the initial information is relevant to the decision being made.', NULL, '[{"label": "TRUE", "text": "TRUE"}, {"label": "FALSE", "text": "FALSE"}, {"label": "NOT GIVEN", "text": "NOT GIVEN"}]'::jsonb, 'FALSE', 'tfng'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'tfng', 4, 'Iyengar and Lepper discovered that offering more jam varieties led to higher sales.', NULL, '[{"label": "TRUE", "text": "TRUE"}, {"label": "FALSE", "text": "FALSE"}, {"label": "NOT GIVEN", "text": "NOT GIVEN"}]'::jsonb, 'FALSE', 'tfng'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'tfng', 5, 'Opt-in organ donation systems usually achieve participation rates above fifty per cent.', NULL, '[{"label": "TRUE", "text": "TRUE"}, {"label": "FALSE", "text": "FALSE"}, {"label": "NOT GIVEN", "text": "NOT GIVEN"}]'::jsonb, 'FALSE', 'tfng'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'matching_headings', 6, 'Paragraph B', NULL, '[{"label": "i", "text": "The limits of traditional economic models"}, {"label": "ii", "text": "How loss affects decisions differently from gain"}, {"label": "iii", "text": "Why first impressions of price are hard to shake"}, {"label": "iv", "text": "When more choice leads to less action"}, {"label": "v", "text": "How default options shape major life decisions"}, {"label": "vi", "text": "Steering behaviour without removing freedom"}, {"label": "vii", "text": "Criticisms of manipulating consumer choices"}]'::jsonb, 'ii', 'matching_headings'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'matching_headings', 7, 'Paragraph C', NULL, '[{"label": "i", "text": "The limits of traditional economic models"}, {"label": "ii", "text": "How loss affects decisions differently from gain"}, {"label": "iii", "text": "Why first impressions of price are hard to shake"}, {"label": "iv", "text": "When more choice leads to less action"}, {"label": "v", "text": "How default options shape major life decisions"}, {"label": "vi", "text": "Steering behaviour without removing freedom"}, {"label": "vii", "text": "Criticisms of manipulating consumer choices"}]'::jsonb, 'iii', 'matching_headings'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'matching_headings', 8, 'Paragraph D', NULL, '[{"label": "i", "text": "The limits of traditional economic models"}, {"label": "ii", "text": "How loss affects decisions differently from gain"}, {"label": "iii", "text": "Why first impressions of price are hard to shake"}, {"label": "iv", "text": "When more choice leads to less action"}, {"label": "v", "text": "How default options shape major life decisions"}, {"label": "vi", "text": "Steering behaviour without removing freedom"}, {"label": "vii", "text": "Criticisms of manipulating consumer choices"}]'::jsonb, 'iv', 'matching_headings'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'matching_headings', 9, 'Paragraph E', NULL, '[{"label": "i", "text": "The limits of traditional economic models"}, {"label": "ii", "text": "How loss affects decisions differently from gain"}, {"label": "iii", "text": "Why first impressions of price are hard to shake"}, {"label": "iv", "text": "When more choice leads to less action"}, {"label": "v", "text": "How default options shape major life decisions"}, {"label": "vi", "text": "Steering behaviour without removing freedom"}, {"label": "vii", "text": "Criticisms of manipulating consumer choices"}]'::jsonb, 'v', 'matching_headings'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'sentence_completion', 10, 'The pain of losing money is felt about twice as strongly as the pleasure of gaining the same amount, an effect called ______.', NULL, NULL, 'loss aversion', 'sentence_completion'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'sentence_completion', 11, 'Iyengar and Lepper compared jam displays with six and ______ varieties.', NULL, NULL, 'twenty-four/twenty four/24', 'sentence_completion'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'sentence_completion', 12, 'Opt-out organ donation countries achieve participation rates above ______ per cent.', NULL, NULL, 'ninety/90', 'sentence_completion'),
('b0000000-0000-4000-8000-000000000002', 'reading', 'sentence_completion', 13, 'Thaler and Sunstein describe interventions that preserve choice as ______ paternalism.', NULL, NULL, 'libertarian', 'sentence_completion');
