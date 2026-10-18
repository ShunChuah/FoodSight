-- Prepare auth.users for login/registration and add session and Google account tables.
BEGIN;

ALTER TABLE auth.users RENAME COLUMN name TO username;

ALTER TABLE auth.users
    ADD COLUMN is_active boolean NOT NULL DEFAULT true,
    ADD COLUMN is_verified boolean NOT NULL DEFAULT false,
    ADD COLUMN is_superuser boolean NOT NULL DEFAULT false;

CREATE TABLE auth.access_token (
    token varchar(43) PRIMARY KEY,
    user_id integer NOT NULL REFERENCES auth.users (user_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_access_token_user ON auth.access_token (user_id);
CREATE INDEX idx_access_token_created ON auth.access_token (created_at);

CREATE TABLE auth.oauth_account (
    id serial PRIMARY KEY,
    user_id integer NOT NULL REFERENCES auth.users (user_id) ON DELETE CASCADE,
    oauth_name varchar(100) NOT NULL,
    access_token text NOT NULL,
    expires_at integer,
    refresh_token text,
    account_id varchar(320) NOT NULL,
    account_email varchar(320) NOT NULL
);
CREATE INDEX idx_oauth_account_user ON auth.oauth_account (user_id);
CREATE INDEX idx_oauth_account_lookup ON auth.oauth_account (oauth_name, account_id);

COMMIT;
