import Logo from "../../assets/foodsightLogo.png";
import DarkModeLogo from "../../assets/foodsightLogoDarkMode.png";
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
