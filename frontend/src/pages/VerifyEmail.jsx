import { useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useSearchParams } from 'react-router-dom'
import { api, errorCode } from '../api/client.js'
import AuthLayout from '../components/AuthLayout.jsx'
import { TextField } from '../components/fields.jsx'
import { Alert, Button, FooterNote, TextLink } from '../components/ui.jsx'
import { GENERIC_ERROR, emailRules } from '../validation.js'

function ResendForm() {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm()
  const [result, setResult] = useState(null)

  const onSubmit = async ({ email }) => {
    try {
      await api.post('/auth/request-verify-token', { email })
      setResult({ tone: 'info', text: 'If that account still needs verifying, a new link is on its way.' })
    } catch {
      setResult({ tone: 'error', text: GENERIC_ERROR })
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-6">
      <Alert>Verification link has expired.</Alert>
      {result && <Alert tone={result.tone}>{result.text}</Alert>}
      <TextField
        label="Email"
        type="email"
        placeholder="abc@gmail.com"
        autoComplete="email"
        error={errors.email?.message}
        {...register('email', emailRules)}
      />
      <Button type="submit" disabled={isSubmitting}>
        Resend Verification Email
      </Button>
    </form>
  )
}

export default function VerifyEmail() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [status, setStatus] = useState(token ? 'checking' : 'expired')
  const requested = useRef(false)

  useEffect(() => {
    // The ref stops React StrictMode's double effect run from sending the token twice.
    if (!token || requested.current) return
    requested.current = true
    api
      .post('/auth/verify', { token })
      .then(() => setStatus('verified'))
      .catch((error) =>
        setStatus(errorCode(error) === 'VERIFY_USER_ALREADY_VERIFIED' ? 'verified' : 'expired'),
      )
  }, [token])

  return (
    <AuthLayout title="Verify Email">
      {status === 'checking' && <p className="text-[0.875rem] text-gray-500 dark:text-gray-300">Verifying your email…</p>}
      {status === 'verified' && <Alert tone="info">Your email is verified. You can log in now.</Alert>}
      {status === 'expired' && <ResendForm />}
      <FooterNote>
        Return To <TextLink to="/login">Login</TextLink>
      </FooterNote>
    </AuthLayout>
  )
}
