-- Users: a profile picture uploaded on the website (Settings → Edit Profile).
-- The image itself is stored here, one row per user; uploading again replaces it.
-- auth.users.profile_picture_url then holds the backend's path to it
-- (/api/v1/users/<user_id>/picture?v=<upload time>), so the frontend shows it the
-- same way as a Google picture link. The allowed types (JPEG, PNG, WebP) and the
-- 2 MB limit are checked by the backend (backend/app/auth/profile.py), not here.
-- Deleting an account deletes its picture.
BEGIN;

CREATE TABLE auth.user_picture (
    user_id      integer     PRIMARY KEY REFERENCES auth.users(user_id) ON DELETE CASCADE,
    image        bytea       NOT NULL,
    content_type varchar(20) NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

COMMIT;
