import { api } from "./client.js";

// The admin review page (backend/app/admin/routes.py). Only admins (is_superuser) may call these.
const get = (url, params) => api.get(url, { params }).then((response) => response.data);
const put = (url, body) => api.put(url, body).then((response) => response.data);
const remove = (url) => api.delete(url).then((response) => response.data);

export const getOverview = () => get("/admin/overview");

export const getGoogleMatches = () => get("/admin/google-matches");
export const getGoogleMatch = (osmId) => get(`/admin/google-matches/${osmId}`);
// pin: "osm" (the pipeline's own rule) or "google" (save Google's pin; same place only)
export const decideGoogleMatch = (osmId, same, note, pin = "osm") => put(`/admin/google-matches/${osmId}`, { same, note, pin });
export const undoGoogleMatch = (osmId) => remove(`/admin/google-matches/${osmId}`);
// A shared Google place, decided as one: osmId gets the place (null: none of them)
export const decideShared = (placeId, osmId, note, pin = "osm") => put(`/admin/google-matches/shared/${placeId}`, { osm_id: osmId, note, pin });
export const undoShared = (placeId) => remove(`/admin/google-matches/shared/${placeId}`);

export const getRemovedRestaurants = () => get("/admin/removed-restaurants");
export const decideRemoved = (osmId, decision, note) => put(`/admin/removed-restaurants/${osmId}`, { decision, note });
export const undoRemoved = (osmId) => remove(`/admin/removed-restaurants/${osmId}`);

export const getNearbyPlaces = (params) => get("/admin/nearby-places", params);
export const getNearbyPlace = (osmType, osmId) => get(`/admin/nearby-places/${osmType}/${osmId}`);
export const getExclusions = () => get("/admin/nearby-exclusions");
export const excludePlace = (osmType, osmId, reason) => put(`/admin/nearby-exclusions/${osmType}/${osmId}`, { reason });
export const removeExclusion = (osmType, osmId) => remove(`/admin/nearby-exclusions/${osmType}/${osmId}`);

export const getHistory = () => get("/admin/history");
export const getReport = (name) => get(`/admin/history/reports/${name}`);

export const getLogDays = () => get("/admin/logs");
export const getLogDay = (day) => get(`/admin/logs/${day}`);
export const getLogText = (day, start, end) => get(`/admin/logs/${day}/text`, { start, end });
