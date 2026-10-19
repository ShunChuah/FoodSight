import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { api, errorCode } from '../api/client.js'
import AuthLayout from '../components/AuthLayout.jsx'
import { TextField } from '../components/fields.jsx'
import { Alert, Button, FooterNote, TextLink } from '../components/ui.jsx'
import { GENERIC_ERROR, emailRules } from '../validation.js'

export default function ForgotPassword() {
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm()
  const [formError, setFormError] = useState(null)
  const [sent, setSent] = useState(false)

  const onSubmit = async ({ email }) => {
    setFormError(null)
    setSent(false)
    try {
      await api.post('/auth/forgot-password', { email })
      setSent(true)
    } catch (requestError) {
      if (errorCode(requestError) === 'FORGOT_PASSWORD_USER_NOT_FOUND') {
        setError('email', { message: 'No account found with this email.' })
      } else {
        setFormError(GENERIC_ERROR)
      }
    }
  }

  return (
    <AuthLayout title="Reset Password">
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-6">
        {sent && <Alert tone="info">Reset link sent. Check your email. It expires in 15 minutes.</Alert>}
        {formError && <Alert>{formError}</Alert>}
        <TextField
          label="Email"
          type="email"
          placeholder="abc@gmail.com"
          autoComplete="email"
          error={errors.email?.message}
          {...register('email', emailRules)}
        />
        <div className="mt-2">
          <Button type="submit" disabled={isSubmitting}>
            Send Reset Link
          </Button>
        </div>
      </form>
      <FooterNote>
        Return To <TextLink to="/login">Login</TextLink>
      </FooterNote>
    </AuthLayout>
  )
}
