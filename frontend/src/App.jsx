import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { GuestRoute, ProtectedRoute } from "./components/RouteGuards.jsx";
import { AuthProvider } from "./context/AuthContext.jsx";
import { ThemeProvider } from "./context/ThemeContext.jsx";
import DashboardPage from "./pages/DashboardPage";
import ForgotPassword from "./pages/ForgotPassword.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import ResetPassword from "./pages/ResetPassword.jsx";
import VerifyEmail from "./pages/VerifyEmail.jsx";

function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
          <Routes>
            <Route element={<GuestRoute />}>
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
            </Route>
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/verify" element={<VerifyEmail />} />
            {/* The chat dashboard is only for logged-in users. */}
            <Route element={<ProtectedRoute />}>
              <Route path="/chat" element={<DashboardPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}

export default App;
