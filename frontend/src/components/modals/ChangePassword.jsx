import { useId, useState } from "react";
import { useForm } from "react-hook-form";
import { api, errorCode } from "../../api/client.js";
import { GENERIC_ERROR, meetsPasswordRule } from "../../validation.js";
import { EyeClosedIcon, EyeIcon } from "../icons.jsx";
import ProfilePicture from "../sidebar/ProfilePicture";
import AccountDialog from "./AccountDialog";

// UC7's own wording; Register and Reset Password keep theirs (validation.js).
const CURRENT_INCORRECT = "Current password is incorrect.";
const COMPLEXITY_ERROR =
  "Passwords must be at least 8 characters and include an uppercase letter, lowercase letter, number, and special character.";
const MISMATCH = "Passwords do not match.";
const SAVED = "Password updated successfully.";

function PasswordRow({ label, error, autoComplete, registration }) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const name = label.toLowerCase();
  return (
    <>
      <label className="account-label" htmlFor={id}>{label}</label>
      <input
        id={id}
        className="account-input"
        type={visible ? "text" : "password"}
        autoComplete={autoComplete}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        {...registration}
      />
      <button
        className="account-icon-button"
        type="button"
        title={visible ? `Hide ${name}` : `Show ${name}`}
        aria-label={visible ? `Hide ${name}` : `Show ${name}`}
        onClick={() => setVisible((current) => !current)}
      >
        {visible ? <EyeClosedIcon /> : <EyeIcon />}
      </button>
      {error && (
        <p id={`${id}-error`} className="account-field-error" role="alert">{error}</p>
      )}
    </>
  );
}

// UC7 Update Password. The backend checks the current password and the rule again,
// then logs out every other browser.
function ChangePassword({ onBack, onClose }) {
  const {
    register,
    handleSubmit,
    getValues,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm();
  const [message, setMessage] = useState(null);

  const onSubmit = async ({ currentPassword, newPassword }) => {
    setMessage(null);
    try {
      await api.post("/users/me/password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      reset();
      setMessage({ tone: "notice", text: SAVED });
    } catch (failure) {
      const code = errorCode(failure);
      if (code === "CHANGE_PASSWORD_WRONG_CURRENT") {
        setError("currentPassword", { message: CURRENT_INCORRECT }, { shouldFocus: true });
      } else if (code === "CHANGE_PASSWORD_INVALID_PASSWORD") {
        setError("newPassword", { message: COMPLEXITY_ERROR }, { shouldFocus: true });
      } else {
        setMessage({ tone: "error", text: GENERIC_ERROR });
      }
    }
  };

  return (
    <AccountDialog title="Change Password" onBack={onBack} onClose={onClose}>
      <div className="account-avatar-box">
        <ProfilePicture className="account-avatar" />
      </div>

      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <div className="account-grid">
          <PasswordRow
            label="Current Password"
            autoComplete="current-password"
            error={errors.currentPassword?.message}
            registration={register("currentPassword", {
              required: "Please enter your current password.",
            })}
          />
          <PasswordRow
            label="New Password"
            autoComplete="new-password"
            error={errors.newPassword?.message}
            registration={register("newPassword", {
              required: "Please enter a new password.",
              validate: (value) => meetsPasswordRule(value) || COMPLEXITY_ERROR,
            })}
          />
          <PasswordRow
            label="Confirm Password"
            autoComplete="new-password"
            error={errors.confirmPassword?.message}
            registration={register("confirmPassword", {
              required: "Please confirm your new password.",
              validate: (value) => value === getValues("newPassword") || MISMATCH,
            })}
          />
        </div>

        <button className="account-primary" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Updating…" : "Update Password"}
        </button>
      </form>

      {message && (
        <p
          className={message.tone === "error" ? "settings-error" : "settings-notice"}
          role={message.tone === "error" ? "alert" : "status"}
        >
          {message.text}
        </p>
      )}
    </AccountDialog>
  );
}

export default ChangePassword;
