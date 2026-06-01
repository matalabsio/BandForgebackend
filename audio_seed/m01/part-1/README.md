# M01 Listening Part 1 audio

Place the MP3 here:

```
full.mp3
```

Upload to R2:

```bash
cd backend
python -m scripts.upload_listening_audio --preset m01
```

R2 key: `listening/m01/part-1/full.mp3`

If you only have the legacy Greenfield file, copy it here or use preset `greenfield` — the API falls back to `listening/greenfield/part-1/full.mp3` when the m01 key is missing.
