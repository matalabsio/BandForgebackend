-- Point M01 listening parts to custom R2 object keys.
-- Reversible by setting back to listening/m01/part-{N}/full.mp3.

update questions
set audio_url = case part
  when 1 then 'test/Listening_S1_Audio.mp3'
  when 2 then 'test/Listening_S2_Audio.mp3'
  when 3 then 'test/Listening_S3_Audio.mp3'
  when 4 then 'test/Listening_S4_Audio.mp3'
  else audio_url
end
where mock_test_id = 'a0000000-0000-4000-8000-000000000001'
  and module = 'listening'
  and part in (1, 2, 3, 4);
