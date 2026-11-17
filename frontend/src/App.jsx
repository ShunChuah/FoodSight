import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AdminRoute, GuestRoute, UserRoute } from "./components/RouteGuards.jsx";
import { AuthProvider } from "./context/AuthContext.jsx";
import { ThemeProvider } from "./context/ThemeContext.jsx";
import AdminOverview from "./components/admin/AdminOverview.jsx";
import AdminReview from "./components/admin/AdminReview.jsx";
import AdminSubmissions from "./components/admin/AdminSubmissions.jsx";
import AdminPage from "./pages/AdminPage.jsx";
import DashboardPage from "./pages/DashboardPage";
import ForgotPassword from "./pages/ForgotPassword.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import ResetPassword from "./pages/ResetPassword.jsx";
import VerifyEmail from "./pages/VerifyEmail.jsx";

// The pipeline review pages (/admin/pipeline/...). Loaded only when an admin opens them,
// so other users never download them.
const PipelineReview = lazy(() => import("./pages/AdminReview.jsx"));

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
            {/* Normal users only (is_superuser false): an admin is sent to /admin */}
            <Route element={<UserRoute />}>
              <Route path="/chat" element={<DashboardPage />} />
            </Route>
            {/* Admins only (is_superuser): business submissions, and the pipeline review pages */}
            <Route element={<AdminRoute />}>
              <Route path="/admin" element={<AdminPage />}>
                <Route index element={<AdminOverview />} />
                <Route path="submissions" element={<AdminSubmissions />} />
                <Route path="submissions/:id" element={<AdminReview />} />
                <Route path="pipeline/:page?" element={<Suspense fallback={null}><PipelineReview /></Suspense>} />
              </Route>
            </Route>
            {/* An unknown address: /chat, which sends an admin on to /admin and a visitor to /login */}
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}

export default App;
