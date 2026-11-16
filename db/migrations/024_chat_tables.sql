-- Chatbot tables (backend/app/model.py), with each chat owned by an account.
--   chat_histories              one row per chat: its owner, title and pin
--   chat_query_states           the conversation's current filters, one row per chat
--   chat_messages               the user's questions and the chatbot's answers
--   chat_message_failures       an answer that failed (AI service, search, timeout)
--   chat_message_quick_replies  suggested follow-up questions under an answer
--   chat_message_maps           the map shown with an answer
--   chat_message_graphs         the knowledge graph evidence shown with an answer
--   chat_message_graph_jobs     an evidence graph still being built
--   user_preferences            per-account settings (the light/dark theme)
-- Replaces 002_chat_owner.sql and 003_user_preferences.sql from the chatbot
-- branch, whose numbers clashed with 002_category_values and 003_area_name_length.
-- The chatbot branch's backend used to create these tables itself (create_all),
-- without the foreign keys to auth.users. So this file is safe to run more than
-- once, and on such a database: it creates only what is missing and adds the two
-- auth.users foreign keys when they are absent.
-- The old chat design (chat_session, chat_query, graph_query_result,
-- insight_response, map_result, map_marker, spatial_analysis_result) is left as it is.
BEGIN;

CREATE TABLE IF NOT EXISTS public.chat_histories (
    id          serial PRIMARY KEY,
    user_id     integer      NOT NULL,
    title       varchar(160) NOT NULL,
    pinned      boolean      NOT NULL DEFAULT false,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_chat_histories_user_id ON public.chat_histories (user_id);
CREATE INDEX IF NOT EXISTS ix_chat_histories_updated_at ON public.chat_histories (updated_at);

CREATE TABLE IF NOT EXISTS public.chat_query_states (
    chat_id  integer PRIMARY KEY REFERENCES public.chat_histories (id) ON DELETE CASCADE,
    state    json    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id          serial PRIMARY KEY,
    chat_id     integer      NOT NULL REFERENCES public.chat_histories (id) ON DELETE CASCADE,
    role        varchar(20)  NOT NULL,
    content     text         NOT NULL,
    map_image   varchar(500),
    created_at  timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_chat_messages_chat_id ON public.chat_messages (chat_id);
CREATE INDEX IF NOT EXISTS ix_chat_messages_created_at ON public.chat_messages (created_at);

CREATE TABLE IF NOT EXISTS public.chat_message_failures (
    message_id  integer     PRIMARY KEY REFERENCES public.chat_messages (id) ON DELETE CASCADE,
    reason      varchar(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS public.chat_message_quick_replies (
    message_id  integer PRIMARY KEY REFERENCES public.chat_messages (id) ON DELETE CASCADE,
    replies     json    NOT NULL
);

CREATE TABLE IF NOT EXISTS public.chat_message_maps (
    message_id  integer PRIMARY KEY REFERENCES public.chat_messages (id) ON DELETE CASCADE,
    data        json    NOT NULL
);

CREATE TABLE IF NOT EXISTS public.chat_message_graphs (
    message_id  integer PRIMARY KEY REFERENCES public.chat_messages (id) ON DELETE CASCADE,
    data        json    NOT NULL
);

CREATE TABLE IF NOT EXISTS public.chat_message_graph_jobs (
    message_id  integer     PRIMARY KEY REFERENCES public.chat_messages (id) ON DELETE CASCADE,
    status      varchar(10) NOT NULL DEFAULT 'pending',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.user_preferences (
    user_id     integer     PRIMARY KEY,
    theme       varchar(10) NOT NULL DEFAULT 'light',
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Deleting an account deletes its chats and settings.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_histories_user_id_fkey') THEN
        ALTER TABLE public.chat_histories
            ADD CONSTRAINT chat_histories_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES auth.users (user_id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_preferences_user_id_fkey') THEN
        ALTER TABLE public.user_preferences
            ADD CONSTRAINT user_preferences_user_id_fkey FOREIGN KEY (user_id)
            REFERENCES auth.users (user_id) ON DELETE CASCADE;
    END IF;
END $$;

COMMIT;
