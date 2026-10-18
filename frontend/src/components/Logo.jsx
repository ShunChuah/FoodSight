import logoDark from '../assets/logo-dark.svg'
import logoLight from '../assets/logo.svg'
import { useTheme } from '../context/ThemeContext.jsx'

export default function Logo({ className }) {
  const { theme } = useTheme()
  return <img src={theme === 'dark' ? logoDark : logoLight} alt="FoodSight" className={className} />
}
