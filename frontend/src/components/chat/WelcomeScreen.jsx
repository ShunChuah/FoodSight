import Logo from "../../assets/foodsightLogo.png";
import DarkModeLogo from "../../assets/foodsightLogoDarkMode.png";
import "../../styles/chat.css";

const ROLES = [
  { value: "diner", label: "I'm looking for food" },
  { value: "business", label: "I'm planning a business" },
];

function WelcomeScreen({ darkMode = false, role = "diner", onRoleChange }) {
  return (
    <div className="welcome-screen">
      <div className="welcome-logo-wrapper">
        <img
          src={darkMode ? DarkModeLogo : Logo}
          alt="FoodSight Logo"
          className="welcome-logo"
        />
      </div>

      <h1>Welcome, explore new restaurants now</h1>

      <div className="welcome-roles" role="group" aria-label="What are you here for?">
        {ROLES.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={role === option.value}
            className={`welcome-role${role === option.value ? " is-active" : ""}`}
            onClick={() => onRoleChange?.(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default WelcomeScreen;
