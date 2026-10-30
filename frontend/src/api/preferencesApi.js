import api from "./client";

export async function fetchThemePreference() {
  const response = await api.get("/preferences");
  return response.data.theme;
}

export async function saveThemePreference(theme) {
  const response = await api.put("/preferences", { theme });
  return response.data.theme;
}
