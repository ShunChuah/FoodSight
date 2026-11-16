import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { api, errorCode, errorReason } from '../api/client.js'
import AuthLayout from '../components/AuthLayout.jsx'
import { PasswordField, TextField } from '../components/fields.jsx'
import { Alert, Button, FooterNote, GoogleButton, TextLink } from '../components/ui.jsx'
import { GENERIC_ERROR, confirmPasswordRules, emailRules, newPasswordRules } from '../validation.js'

export default function Register() {
  const {
    register,
    handleSubmit,
    getValues,
    setError,
    formState: { errors, isSubmitting },
  } = useForm()
  const [formError, setFormError] = useState(null)
  const [registeredEmail, setRegisteredEmail] = useState(null)

  const onSubmit = async ({ username, email, password }) => {
    setFormError(null)
    try {
      await api.post('/auth/register', { username: username.trim(), email, password })
      setRegisteredEmail(email)
    } catch (requestError) {
      const code = errorCode(requestError)
      if (code === 'REGISTER_USER_ALREADY_EXISTS') {
        setError('email', { message: 'Email already in use.' })
      } else if (code === 'REGISTER_INVALID_PASSWORD') {
        setError('password', { message: errorReason(requestError) })
      } else {
        setFormError(GENERIC_ERROR)
      }
    }
  }

  if (registeredEmail) {
    return (
      <AuthLayout title="Check your email">
        <p className="text-[0.875rem] text-gray-500 dark:text-gray-300">
          We sent a verification link to <span className="font-semibold">{registeredEmail}</span>. Open it
          within 15 minutes to activate your account.
        </p>
        <FooterNote>
          Return To <TextLink to="/login">Login</TextLink>
        </FooterNote>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Create an account">
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
        {formError && <Alert>{formError}</Alert>}
        <TextField
          label="Username"
          placeholder="Enter your username"
          autoComplete="name"
          error={errors.username?.message}
          {...register('username', {
            validate: (value) => value.trim().length > 0 || 'Username is required.',
            maxLength: { value: 150, message: 'Username must be 150 characters or fewer.' },
          })}
        />
        <TextField
          label="Email"
          type="email"
          placeholder="abc@gmail.com"
          autoComplete="email"
          error={errors.email?.message}
          {...register('email', emailRules)}
        />
        <PasswordField
          label="Password"
          placeholder="Enter your password"
          autoComplete="new-password"
          error={errors.password?.message}
          {...register('password', newPasswordRules)}
        />
        <PasswordField
          label="Confirm Password"
          placeholder="Re-enter your password"
          autoComplete="new-password"
          error={errors.confirmPassword?.message}
          {...register('confirmPassword', confirmPasswordRules(getValues))}
        />
        <div className="mt-2">
          <Button type="submit" disabled={isSubmitting}>
            Create account
          </Button>
        </div>
      </form>
      <GoogleButton />
      <FooterNote>
        Already Have An Account ? <TextLink to="/login">Log In</TextLink>
      </FooterNote>
    </AuthLayout>
  )
}
