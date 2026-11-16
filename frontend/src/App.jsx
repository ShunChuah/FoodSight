import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AdminRoute, GuestRoute, ProtectedRoute } from "./components/RouteGuards.jsx";
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

// The pipeline review page (/admin/pipeline). Loaded only when an admin opens it,
// so other users never download it.
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
            <Route element={<ProtectedRoute />}>
              <Route path="/chat" element={<DashboardPage />} />
            </Route>
            {/* Admins only (is_superuser): business submissions, and the pipeline review page */}
            <Route element={<AdminRoute />}>
              <Route path="/admin" element={<AdminPage />}>
                <Route index element={<AdminOverview />} />
                <Route path="submissions" element={<AdminSubmissions />} />
                <Route path="submissions/:id" element={<AdminReview />} />
              </Route>
              <Route path="/admin/pipeline" element={<Suspense fallback={null}><PipelineReview /></Suspense>} />
            </Route>
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}

export default App;
