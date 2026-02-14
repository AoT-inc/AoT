import axios from 'axios'

// Create axios instance
// We use relative paths because the React app will be served from the same domain as Flask
const api = axios.create({
  baseURL: '/',
  withCredentials: true,
  headers: {
    'Accept': 'application/vnd.aot.v1+json',
  }
})

// Add response interceptor for better error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Check for 401/403 (Auth issues)
    if (error.response && (error.response.status === 401 || error.response.status === 403)) {
        console.error("Authentication Error", error);
        // Maybe dispatch an event or redirect
    }
    return Promise.reject(error);
  }
);

export const fetchNotes = async (targetId) => {
  if (!targetId) throw new Error("targetId is required");
  const response = await api.get(`/notes/target/${targetId}`);
  return response.data;
}

export const createNote = async (formData) => {
  // formData should include: note, target_id, target_type, files, gps_lat, gps_lng
  const response = await api.post('/notes/create', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
  return response.data;
}

export const fetchTags = async () => {
  const response = await api.get('/notes/tags');
  return response.data;
}

export default api
