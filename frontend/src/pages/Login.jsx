import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, errorCode } from '../api/client.js'
import AuthLayout from '../components/AuthLayout.jsx'
import { PasswordField, TextField } from '../components/fields.jsx'
import { Alert, Button, FooterNote, GoogleButton, TextLink } from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { GENERIC_ERROR, emailRules } from '../validation.js'

export default function Login() {
  const { refresh, notice, clearNotice } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm()
  const [error, setError] = useState(notice)
  const [unverified, setUnverified] = useState(false)
  const [info, setInfo] = useState(location.state?.message ?? null)

  useEffect(() => clearNotice, [clearNotice])

  const onSubmit = async ({ email, password }) => {
    setError(null)
    setInfo(null)
    setUnverified(false)
    try {
      // The login endpoint takes a form body and calls the email field "username".
      await api.post('/auth/login', new URLSearchParams({ username: email, password }))
      await refresh()
      navigate('/chat', { replace: true })
    } catch (requestError) {
      const code = errorCode(requestError)
      if (code === 'LOGIN_USER_NOT_VERIFIED') setUnverified(true)
      else setError(code === 'LOGIN_BAD_CREDENTIALS' ? 'Invalid email or password.' : GENERIC_ERROR)
    }
  }

  const resendVerification = async () => {
    try {
      await api.post('/auth/request-verify-token', { email: getValues('email') })
      setUnverified(false)
      setInfo('Verification email sent. Check your inbox.')
    } catch {
      setUnverified(false)
      setError(GENERIC_ERROR)
    }
  }

  return (
    <AuthLayout title="Login to your account">
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-6">
        {info && <Alert tone="info">{info}</Alert>}
        {error && <Alert>{error}</Alert>}
        {unverified && (
          <Alert>
            Please verify your email before logging in.{' '}
            <button type="button" onClick={resendVerification} className="cursor-pointer font-semibold underline">
              Resend verification email
            </button>
          </Alert>
        )}
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
          autoComplete="current-password"
          labelAction={<TextLink to="/forgot-password">Forgot ?</TextLink>}
          error={errors.password?.message}
          {...register('password', { required: 'Password is required.' })}
        />
        <div className="mt-2">
          <Button type="submit" disabled={isSubmitting}>
            Login now
          </Button>
        </div>
      </form>
      <GoogleButton />
      <FooterNote>
        Don’t Have An Account ? <TextLink to="/register">Sign Up</TextLink>
      </FooterNote>
    </AuthLayout>
  )
}
