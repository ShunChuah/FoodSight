import TopBar from './TopBar.jsx'

export default function AuthLayout({ title, children }) {
  return (
    <div className="page-bg flex min-h-screen min-w-[68.75rem] flex-col">
      <TopBar />
      <main className="flex flex-1 flex-col items-center justify-center py-6">
        <section className="flex min-h-[38.75rem] w-[33.75rem] flex-col justify-center rounded-[1.25rem] border border-gray-200 bg-white px-[4.5rem] py-14 shadow-[40px_40px_60px_rgb(228_230_234_/_0.74)] dark:border-line-dark dark:bg-surface-dark dark:shadow-none">
          <h1 className="mb-6 text-[1.75rem] font-bold text-ink dark:text-white">{title}</h1>
          {children}
        </section>
      </main>
    </div>
  )
}
