-- Users: a link to the account's profile picture. Filled with the Google
-- profile picture on the account's first sign-in with Google (a new Google
-- account, or an email account linking Google for the first time), and only
-- when the account has no picture yet. Empty (NULL) means no picture: the
-- frontend then shows its default image, as for every email-registered account.
BEGIN;

ALTER TABLE auth.users ADD COLUMN profile_picture_url varchar(500);

COMMIT;
