import { useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import avatar from '../assets/avatar.svg'
import { useAuth } from '../context/AuthContext.jsx'
import { useTheme } from '../context/ThemeContext.jsx'
import Logo from './Logo.jsx'
import { MoonIcon } from './icons.jsx'

const navLink = ({ isActive }) =>
  `text-[0.875rem] text-ink hover:text-brand dark:text-white ${isActive ? 'font-semibold' : 'font-normal'}`

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const dark = theme === 'dark'
  return (
    <div className="flex h-11 items-center gap-3 rounded-[0.625rem] border border-gray-200 bg-white pl-3 pr-2 text-ink dark:border-line-dark dark:bg-surface-dark dark:text-white">
      <MoonIcon />
      <span className="text-[0.875rem] font-normal">Dark Mode</span>
      <button
        type="button"
        role="switch"
        aria-checked={dark}
        aria-label="Dark mode"
        onClick={toggleTheme}
        className={`relative ml-1 h-[1.625rem] w-[3.25rem] cursor-pointer rounded-full transition-colors ${dark ? 'bg-[#5a321f]' : 'bg-gray-200'}`}
      >
        <span
          className={`absolute top-1 left-1 size-[1.125rem] rounded-full bg-white transition-transform ${dark ? 'translate-x-[1.625rem]' : ''}`}
        />
      </button>
    </div>
  )
}

const avatarBox = '-my-2 -mr-2 ml-12 size-[4.125rem] max-w-none'

// The account's profile picture, drawn like the default avatar (a circle with a
// light grey edge in the same box). No picture, or one that fails to load,
// shows the default avatar. referrerPolicy: Google's image server can refuse a
// request that says which page it came from.
function Avatar({ url }) {
  const [failed, setFailed] = useState(false)
  if (!url || failed) {
    return <img src={avatar} alt="" className={avatarBox} />
  }
  return (
    <span className={`${avatarBox} flex items-center justify-center`}>
      <img
        src={url}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
        className="size-[3.1875rem] rounded-full border border-zinc-200 object-cover"
      />
    </span>
  )
}

export default function TopBar() {
  const { user, logout } = useAuth()
  return (
    <header className="flex items-center justify-between px-20 py-5">
      <Link to="/">
        <Logo className="h-[3.25rem] w-auto" />
      </Link>
      <div className="flex items-center">
        <nav className="flex items-center gap-4">
          {user ? (
            <>
              <span className="text-[0.875rem] font-medium text-ink dark:text-white">{user.username}</span>
              <button
                type="button"
                onClick={logout}
                className="cursor-pointer text-[0.875rem] font-normal text-ink hover:text-brand dark:text-white"
              >
                Log out
              </button>
            </>
          ) : (
            <>
              <NavLink to="/login" className={navLink}>
                Login
              </NavLink>
              <NavLink to="/register" className={navLink}>
                Sign Up
              </NavLink>
            </>
          )}
        </nav>
        <div className="ml-16">
          <ThemeToggle />
        </div>
        {/* Only for a logged-in user: a visitor has no picture to show.
            key: a new picture link starts fresh, even after an earlier one failed */}
        {user && <Avatar key={user.profile_picture_url || 'default'} url={user.profile_picture_url} />}
      </div>
    </header>
  )
}
