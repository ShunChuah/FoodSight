-- Cinematic AI tour tables (backend/app/model.py), from the chatbot branch's PR #3:
--   chat_message_tours  the tour's words for an answer, written once by the model (tour_script.py)
--   narration_audio     spoken tour lines, kept so the same words are never paid for twice (speech.py)
-- That branch created these with create_all, which this branch removed. Safe to run more
-- than once: it creates only what is missing.
BEGIN;

CREATE TABLE IF NOT EXISTS public.chat_message_tours (
    message_id  integer PRIMARY KEY REFERENCES public.chat_messages (id) ON DELETE CASCADE,
    data        json    NOT NULL
);

CREATE TABLE IF NOT EXISTS public.narration_audio (
    key         varchar(64) PRIMARY KEY,
    audio       bytea       NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

COMMIT;
