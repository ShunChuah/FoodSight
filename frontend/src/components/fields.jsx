import { useId, useState } from 'react'
import { EyeIcon, EyeOffIcon } from './icons.jsx'

const inputClass = (error) =>
  `h-12 w-full rounded-[10px] border bg-white px-4 text-[0.875rem] text-ink outline-none placeholder:text-gray-500 focus:ring-2 dark:bg-page-dark dark:text-white dark:placeholder:text-muted-dark ${
    error
      ? 'border-red-500 focus:ring-red-500/20'
      : 'border-gray-200 focus:border-brand/40 focus:ring-brand/15 dark:border-line-dark dark:focus:border-brand/60 dark:focus:ring-brand/20'
  }`

function Field({ id, label, labelAction, error, children }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <label htmlFor={id} className="text-[0.875rem] text-ink dark:text-white">
          {label}
        </label>
        {labelAction}
      </div>
      {children}
      {error && (
        <p id={`${id}-error`} role="alert" className="mt-1.5 text-[0.8125rem] text-red-500">
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
          className="absolute inset-y-0 right-3 flex cursor-pointer items-center text-gray-500 hover:text-ink dark:text-muted-dark dark:hover:text-white"
        >
          {visible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      </div>
    </Field>
  )
}
