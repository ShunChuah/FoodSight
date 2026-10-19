-- Give every chat an owner so each account only sees its own chats.
-- Safe to run more than once. Run after 001_auth.sql (or the team schema).
BEGIN;

ALTER TABLE public.chat_histories ADD COLUMN IF NOT EXISTS user_id integer;

-- Chats saved before login existed go to the first account; with no accounts they are removed.
UPDATE public.chat_histories SET user_id = (SELECT min(user_id) FROM auth.users) WHERE user_id IS NULL;
DELETE FROM public.chat_histories WHERE user_id IS NULL;

ALTER TABLE public.chat_histories ALTER COLUMN user_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_chat_histories_user_id ON public.chat_histories (user_id);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_histories_user_id_fkey') THEN
        ALTER TABLE public.chat_histories
            ADD CONSTRAINT chat_histories_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES auth.users (user_id) ON DELETE CASCADE;
    END IF;
END $$;

COMMIT;
