import { api } from "./client.js";

// Register Business (backend/app/business/routes.py) and its admin review (admin_routes.py).
const data = (response) => response.data;

export const DOCUMENT_FIELDS = ["ssmCertificate", "premisesLicence", "storefrontPhoto", "halalCertificate"];

export const getBusinessOptions = () => api.get("/business/options").then(data);
export const getAreaForPin = ({ latitude, longitude }) => api.get("/business/area", { params: { latitude, longitude } }).then(data);

export const getMySubmissions = () => api.get("/business/submissions").then(data);

// The form goes as JSON beside the files. A file field holds a File (a new upload, sent as a
// file), a saved file from the server (kept: sent as true) or null (none, or removed).
export function sendSubmission(form, submissionId = null) {
  const body = new FormData();
  const fields = { ...form };
  for (const field of DOCUMENT_FIELDS) {
    const value = form[field];
    if (value instanceof File) body.append(field, value);
    fields[field] = value ? true : null;
  }
  body.append("form", JSON.stringify(fields));
  const request = submissionId
    ? api.put(`/business/submissions/${submissionId}`, body)
    : api.post("/business/submissions", body);
  return request.then(data);
}

// Admins only (is_superuser)
export const getAdminSubmissions = () => api.get("/admin/submissions").then(data);
export const getAdminSubmission = (id) => api.get(`/admin/submissions/${id}`).then(data);
export const markField = (id, field, state, note = "") => api.put(`/admin/submissions/${id}/checks/${field}`, { state, note }).then(data);
export const decideSubmission = (id, decision) => api.post(`/admin/submissions/${id}/decision`, { decision }).then(data);

// {field: message} from a refused submission (422), or null for any other error.
export function submissionFieldErrors(error) {
  const detail = error.response?.data?.detail;
  return detail && typeof detail === "object" && detail.fields && !Array.isArray(detail.fields) ? detail.fields : null;
}
