import Logo from "../../assets/logo.svg";
import DarkModeLogo from "../../assets/logo-dark.svg";
import "../../styles/chat.css";

function WelcomeScreen({ darkMode = false }) {
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
    </div>
  );
}

export default WelcomeScreen;
