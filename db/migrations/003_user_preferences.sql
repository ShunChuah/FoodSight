-- Per-account settings (the light/dark theme), restored on the next login.
-- Safe to run more than once. The backend also creates the table at start-up, without the foreign key.
BEGIN;

CREATE TABLE IF NOT EXISTS public.user_preferences (
    user_id integer PRIMARY KEY,
    theme varchar(10) NOT NULL DEFAULT 'light',
    updated_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_preferences_user_id_fkey') THEN
        ALTER TABLE public.user_preferences
            ADD CONSTRAINT user_preferences_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES auth.users (user_id) ON DELETE CASCADE;
    END IF;
END $$;

COMMIT;
