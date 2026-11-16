import { useEffect, useId, useRef, useState } from "react";
import { Pencil } from "lucide-react";
import { api, errorCode } from "../../api/client.js";
import { useAuth } from "../../context/AuthContext.jsx";
import { Picture } from "../sidebar/ProfilePicture";
import AccountDialog from "./AccountDialog";

const LOAD_ERROR = "Unable to load profile. Please try again.";
const USERNAME_EMPTY = "Username cannot be empty.";
const USERNAME_SAVED = "Username updated successfully.";
const USERNAME_FAILED = "Unable to update username. Please try again.";
const USERNAME_MAX = 150; // auth.users.username is varchar(150)

const PICTURE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const PICTURE_MAX_BYTES = 2 * 1024 * 1024; // also PICTURE_MAX_BYTES in backend/app/auth/profile.py
const PICTURE_BAD_TYPE = "Please choose a JPG, PNG or WebP image.";
const PICTURE_TOO_LARGE = "The picture must be 2 MB or smaller.";
const PICTURE_SAVED = "Profile picture updated successfully.";
const PICTURE_FAILED = "Unable to update profile picture. Please try again.";

const notice = (text) => ({ tone: "notice", text });
const error = (text) => ({ tone: "error", text });

// UC5 View Profile, UC6 Update Username, and changing the profile picture.
function Profile({ onBack, onClose }) {
  const { updateUser } = useAuth();
  const [profile, setProfile] = useState(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState(null);
  const nameRef = useRef(null);
  const fileRef = useRef(null);
  const nameId = useId();
  const labelId = useId();
  const emailLabelId = useId();
  const messageId = useId();

  // UC5 step 2: read the profile from the database every time the dialog opens.
  useEffect(() => {
    let active = true;
    api
      .get("/users/me")
      .then(({ data }) => {
        if (!active) return;
        setProfile(data);
        setName(data.username);
        updateUser(data);
      })
      .catch((failure) => {
        console.error("Failed to load profile", failure);
        if (active) setLoadFailed(true);
      });
    return () => {
      active = false;
    };
  }, [attempt, updateUser]);

  useEffect(() => {
    if (editing) nameRef.current?.focus();
  }, [editing]);

  const retryLoad = () => {
    setLoadFailed(false);
    setAttempt((current) => current + 1);
  };

  // The pencil unlocks the name (UC6 step 2); pressing it again puts the saved name back.
  const toggleEditing = () => {
    if (editing) setName(profile.username);
    setEditing(!editing);
    setMessage(null);
  };

  const saveUsername = async (event) => {
    event.preventDefault();
    if (!editing || saving) return;
    const username = name.trim();
    if (!username) {
      setMessage(error(USERNAME_EMPTY));
      nameRef.current?.focus();
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const { data } = await api.patch("/users/me", { username });
      setProfile(data);
      setName(data.username);
      updateUser(data);
      setEditing(false);
      setMessage(notice(USERNAME_SAVED));
    } catch (failure) {
      setMessage(error(errorCode(failure) === "USERNAME_EMPTY" ? USERNAME_EMPTY : USERNAME_FAILED));
    } finally {
      setSaving(false);
    }
  };

  const uploadPicture = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // so choosing the same file again still uploads it
    if (!file) return;
    if (!PICTURE_TYPES.includes(file.type)) return setMessage(error(PICTURE_BAD_TYPE));
    if (file.size > PICTURE_MAX_BYTES) return setMessage(error(PICTURE_TOO_LARGE));
    setUploading(true);
    setMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post("/users/me/picture", form);
      setProfile(data);
      updateUser(data);
      setMessage(notice(PICTURE_SAVED));
    } catch (failure) {
      const code = errorCode(failure);
      setMessage(
        error(
          code === "PICTURE_BAD_TYPE"
            ? PICTURE_BAD_TYPE
            : code === "PICTURE_TOO_LARGE"
              ? PICTURE_TOO_LARGE
              : PICTURE_FAILED,
        ),
      );
    } finally {
      setUploading(false);
    }
  };

  let body;
  if (loadFailed) {
    body = (
      <div className="account-load">
        <p className="settings-error" role="alert">{LOAD_ERROR}</p>
        <button className="account-primary" type="button" onClick={retryLoad}>
          Try again
        </button>
      </div>
    );
  } else if (!profile) {
    body = (
      <div className="account-load">
        <p className="settings-notice" role="status">Loading profile…</p>
      </div>
    );
  } else {
    const nameInvalid = message?.text === USERNAME_EMPTY;
    body = (
      <>
        <div className="account-avatar-box">
          <button
            className="account-avatar-button"
            type="button"
            title="Change profile picture"
            aria-label="Change profile picture"
            aria-busy={uploading || undefined}
            disabled={uploading}
            onClick={() => fileRef.current?.click()}
          >
            <Picture
              key={profile.profile_picture_url || "default"}
              url={profile.profile_picture_url}
              className="account-avatar"
            />
            <span className="account-avatar-badge" aria-hidden="true">
              <Pencil />
            </span>
          </button>
          <input
            ref={fileRef}
            type="file"
            accept={PICTURE_TYPES.join(",")}
            hidden
            onChange={uploadPicture}
          />
        </div>

        <form onSubmit={saveUsername} noValidate>
          <div className="account-grid">
            <span className="account-label" id={emailLabelId}>Email</span>
            {/* Read only, like the locked name; title shows a long address in full. */}
            <span
              className="account-input account-input-locked account-email"
              aria-labelledby={emailLabelId}
              title={profile.email}
            >
              {profile.email}
            </span>

            <label
              className="account-label"
              id={labelId}
              htmlFor={editing ? nameId : undefined}
            >
              Name
            </label>
            {/* Plain text until the pencil is pressed, so the box cannot be clicked into,
                selected or show a text cursor; a real input only while editing. */}
            {editing ? (
              <input
                ref={nameRef}
                id={nameId}
                className="account-input"
                value={name}
                maxLength={USERNAME_MAX}
                autoComplete="nickname"
                disabled={saving}
                aria-invalid={nameInvalid}
                aria-describedby={message ? messageId : undefined}
                onChange={(event) => setName(event.target.value)}
              />
            ) : (
              <span className="account-input account-input-locked" aria-labelledby={labelId}>
                {name}
              </span>
            )}
            <button
              className="account-icon-button"
              type="button"
              title={editing ? "Cancel editing" : "Edit username"}
              aria-label={editing ? "Cancel editing username" : "Edit username"}
              aria-pressed={editing}
              disabled={saving}
              onClick={toggleEditing}
            >
              <Pencil aria-hidden="true" />
            </button>
          </div>

          <button className="account-primary" type="submit" disabled={!editing || saving}>
            {saving ? "Updating…" : "Update Username"}
          </button>
        </form>
      </>
    );
  }

  return (
    <AccountDialog title="Profile" onBack={onBack} onClose={onClose}>
      {body}
      {uploading && <p className="settings-notice" role="status">Uploading picture…</p>}
      {message && (
        <p
          id={messageId}
          className={message.tone === "error" ? "settings-error" : "settings-notice"}
          role={message.tone === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}
    </AccountDialog>
  );
}

export default Profile;
