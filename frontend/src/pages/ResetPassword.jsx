import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, errorCode, errorReason } from '../api/client.js'
import AuthLayout from '../components/AuthLayout.jsx'
import { PasswordField } from '../components/fields.jsx'
import { Alert, Button, FooterNote, TextLink } from '../components/ui.jsx'
import { GENERIC_ERROR, confirmPasswordRules, newPasswordRules } from '../validation.js'

export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const navigate = useNavigate()
  const {
    register,
    handleSubmit,
    getValues,
    setError,
    formState: { errors, isSubmitting },
  } = useForm()
  const [formError, setFormError] = useState(null)
  const [expired, setExpired] = useState(!token)

  const onSubmit = async ({ password }) => {
    setFormError(null)
    try {
      await api.post('/auth/reset-password', { token, password })
      navigate('/login', { replace: true, state: { message: 'Password updated. Please log in.' } })
    } catch (requestError) {
      const code = errorCode(requestError)
      if (code === 'RESET_PASSWORD_BAD_TOKEN') setExpired(true)
      else if (code === 'RESET_PASSWORD_INVALID_PASSWORD') {
        setError('password', { message: errorReason(requestError) })
      } else setFormError(GENERIC_ERROR)
    }
  }

  if (expired) {
    return (
      <AuthLayout title="Reset Password">
        <Alert>Reset link has expired.</Alert>
        <FooterNote>
          <TextLink to="/forgot-password">Request a new reset link</TextLink>
        </FooterNote>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Set New Password">
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-6">
        {formError && <Alert>{formError}</Alert>}
        <PasswordField
          label="New Password"
          placeholder="Enter your new password"
          autoComplete="new-password"
          error={errors.password?.message}
          {...register('password', newPasswordRules)}
        />
        <PasswordField
          label="Confirm Password"
          placeholder="Re-enter your new password"
          autoComplete="new-password"
          error={errors.confirmPassword?.message}
          {...register('confirmPassword', confirmPasswordRules(getValues))}
        />
        <div className="mt-2">
          <Button type="submit" disabled={isSubmitting}>
            Update Password
          </Button>
        </div>
      </form>
      <FooterNote>
        Return To <TextLink to="/login">Login</TextLink>
      </FooterNote>
    </AuthLayout>
  )
}
