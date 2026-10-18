export const GENERIC_ERROR = 'Something went wrong. Please try again.'

export const emailRules = {
  required: 'Email is required.',
  pattern: { value: /^\S+@\S+\.\S+$/, message: 'Enter a valid email address.' },
}

// Mirrors PASSWORD_RULES in backend/app/auth/manager.py, which is the real check.
export const newPasswordRules = {
  required: 'Password is required.',
  validate: (value) =>
    (value.length >= 8 &&
      /[A-Z]/.test(value) &&
      /[a-z]/.test(value) &&
      /\d/.test(value) &&
      /[^A-Za-z0-9]/.test(value)) ||
    'Use at least 8 characters with an uppercase letter, a lowercase letter, a number and a special character.',
}

export const confirmPasswordRules = (getValues) => ({
  required: 'Please confirm your password.',
  validate: (value) => value === getValues('password') || 'Passwords do not match.',
})
