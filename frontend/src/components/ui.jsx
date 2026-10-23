import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errorCode } from '../api/client.js'
import { GENERIC_ERROR } from '../validation.js'
import { GoogleIcon } from './icons.jsx'

export function Button({ children, ...buttonProps }) {
  return (
    <button
      className="h-12 w-full cursor-pointer rounded-[10px] bg-brand text-[0.875rem] font-semibold text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-60"
      {...buttonProps}
    >
      {children}
    </button>
  )
}

export function Alert({ tone = 'error', children }) {
  const tones = {
    error: 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300',
    info: 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-300',
  }
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`rounded-[10px] border px-4 py-3 text-[0.8125rem] ${tones[tone]}`}>
      {children}
    </div>
  )
}

export function TextLink({ to, children }) {
  return (
    <Link to={to} className="text-brand hover:underline">
      {children}
    </Link>
  )
}

export function FooterNote({ children }) {
  return <p className="mt-6 text-center text-[0.875rem] text-gray-400">{children}</p>
}

export function GoogleButton() {
  const [error, setError] = useState(null)

  const start = async () => {
    setError(null)
    try {
      const { data } = await api.get('/auth/google/authorize')
      window.location.assign(data.authorization_url)
    } catch (requestError) {
      setError(
        errorCode(requestError) === 'GOOGLE_NOT_CONFIGURED'
          ? 'Google login is not set up yet.'
          : GENERIC_ERROR,
      )
    }
  }

  return (
    <div className="mt-6">
      <button
        type="button"
        onClick={start}
        className="flex h-12 w-full cursor-pointer items-center justify-center gap-2 rounded-[10px] border border-[#fdc9b5] bg-brand-soft text-[0.875rem] font-semibold text-brand transition-colors hover:bg-[#ffe9df] dark:border-line-dark dark:bg-[#27272a] dark:hover:bg-[#2a1b16]"
      >
        <GoogleIcon />
        Continue with Google
      </button>
      {error && (
        <p role="alert" className="mt-1.5 text-center text-[0.8125rem] text-red-500">
          {error}
        </p>
      )}
    </div>
  )
}
