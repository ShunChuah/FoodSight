import TopBar from '../components/TopBar.jsx'
import { useAuth } from '../context/AuthContext.jsx'

export default function Chat() {
  const { user } = useAuth()
  return (
    <div className="page-bg min-h-screen min-w-[68.75rem]">
      <TopBar />
      <main className="flex flex-col items-center pt-40 text-center">
        <h1 className="text-[1.75rem] font-semibold text-ink dark:text-white">Welcome, {user.username}</h1>
        <p className="mt-3 text-base text-gray-500 dark:text-gray-300">The chat interface will be built here.</p>
      </main>
    </div>
  )
}
