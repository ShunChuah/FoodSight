import { useId, useState } from 'react'
import { EyeIcon, EyeOffIcon } from './icons.jsx'

const inputClass = (error) =>
  `h-12 w-full rounded-md border bg-white px-4 text-[0.9375rem] text-ink outline-none placeholder:text-gray-400 focus:ring-2 dark:bg-transparent dark:text-white dark:placeholder:text-gray-500 ${
    error
      ? 'border-red-500 focus:ring-red-500/20'
      : 'border-gray-300 focus:border-brand/40 focus:ring-brand/15 dark:border-white/80 dark:focus:border-white dark:focus:ring-white/40'
  }`

function Field({ id, label, labelAction, error, children }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <label htmlFor={id} className="text-base text-ink dark:text-white">
          {label}
        </label>
        {labelAction}
      </div>
      {children}
      {error && (
        <p id={`${id}-error`} role="alert" className="mt-1.5 text-sm text-red-500">
          {error}
        </p>
      )}
    </div>
  )
}

export function TextField({ label, labelAction, error, ...inputProps }) {
  const id = useId()
  return (
    <Field id={id} label={label} labelAction={labelAction} error={error}>
      <input
        id={id}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        className={inputClass(error)}
        {...inputProps}
      />
    </Field>
  )
}

export function PasswordField({ label, labelAction, error, ...inputProps }) {
  const id = useId()
  const [visible, setVisible] = useState(false)
  return (
    <Field id={id} label={label} labelAction={labelAction} error={error}>
      <div className="relative">
        <input
          id={id}
          type={visible ? 'text' : 'password'}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          className={`${inputClass(error)} pr-12`}
          {...inputProps}
        />
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          className="absolute inset-y-0 right-3 flex cursor-pointer items-center text-gray-500 hover:text-ink dark:text-white dark:hover:text-gray-300"
        >
          {visible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      </div>
    </Field>
  )
}
