/**
 * Axios API client.
 * Base URL from VITE_API_URL env var (default: http://127.0.0.1:8000).
 * All error handling is centralised here – surfaces backend `detail` messages.
 */
import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 60_000,
});

/** Intercept every response error and throw a normalised Error with the backend detail. */
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail =
      err.response?.data?.detail ??
      err.response?.data?.message ??
      err.message ??
      'Unknown error';
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail);
    const enhanced = new Error(message);
    enhanced.status = err.response?.status;
    enhanced.raw = err;
    return Promise.reject(enhanced);
  },
);

export default api;

// ── Route helpers ─────────────────────────────────────────────────────────────

export const health = () => api.get('/health').then((r) => r.data);

export const listDatasets = () => api.get('/datasets').then((r) => r.data);

export const getDataset = (id) => api.get(`/datasets/${id}`).then((r) => r.data);

export const getDatasetVersions = (id) =>
  api.get(`/datasets/${id}/versions`).then((r) => r.data);

export const getVersion = (id) => api.get(`/versions/${id}`).then((r) => r.data);

export const getLineage = (id) =>
  api.get(`/versions/${id}/lineage`).then((r) => r.data);

/** Verify stored file (GET). */
export const verifyGet = (id) =>
  api.get(`/versions/${id}/verify`).then((r) => r.data);

/** Verify uploaded file against a version (POST multipart). */
export const verifyPost = (id, file) => {
  const fd = new FormData();
  fd.append('file', file);
  return api
    .post(`/versions/${id}/verify`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
};

/**
 * Upload a root dataset (POST /datasets).
 * @param {File} file
 * @param {number} chunkRows
 * @param {function} onProgress  (0–100)
 */
export const uploadDataset = (file, chunkRows = 1000, onProgress) => {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('chunk_rows', String(chunkRows));
  return api
    .post('/datasets', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100));
      },
    })
    .then((r) => r.data);
};

/** Run tamper-demo (POST /versions/{id}/tamper-demo). */
export const tamperDemo = (versionId, attack, fraction, seed) =>
  api
    .post(`/versions/${versionId}/tamper-demo`, { attack, fraction, seed })
    .then((r) => r.data);

export const getExperiment = (runId) =>
  api.get(`/experiments/${runId}`).then((r) => r.data);

export const getVersionExperiments = (versionId) =>
  api.get(`/versions/${versionId}/experiments`).then((r) => r.data);
