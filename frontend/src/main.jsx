import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import "./styles/notice.css";
import "./index.css";
import "./styles/global.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary fallback={(
      <main className="app-crash">
        <div className="app-crash-card" role="alert">
          <h1>Something went wrong</h1>
          <p>FoodSight couldn't show this page. Your chats are saved.</p>
          <button type="button" onClick={() => window.location.reload()}>Reload</button>
        </div>
      </main>
    )}>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
