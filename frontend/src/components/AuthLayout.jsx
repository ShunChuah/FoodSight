import Logo from './Logo.jsx'
import TopBar from './TopBar.jsx'

export default function AuthLayout({ title, children }) {
  return (
    <div className="page-bg min-h-screen min-w-[68.75rem] pb-6">
      <TopBar />
      <main className="flex flex-col items-center pt-16">
        <Logo className="h-[5.625rem] w-auto" />
        <section className="mt-7 flex min-h-[38.75rem] w-[33.75rem] flex-col justify-center rounded-3xl border border-gray-200 bg-white px-[4.5rem] py-14 shadow-[0_24px_60px_-20px_rgb(0_0_0_/_0.18)] dark:border-white dark:bg-surface-dark dark:shadow-none">
          <h1 className="mb-6 text-[1.75rem] font-semibold text-ink dark:text-white">{title}</h1>
          {children}
        </section>
      </main>
    </div>
  )
}
