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

// ─── 노트 구간 → 예정 (링크) ───────────────────────────────────────────────
//
// **노트 목록이 링크를 함께 싣는다**(`fetchNotes`) — 여기 조회 함수가 없는
// 것은 빠뜨린 것이 아니다. 따로 부르면 노트 수만큼 왕복이 생기고, 목록이
// 먼저 그려진 뒤 하이라이트가 뒤늦게 얹혀 글이 한 번 튄다.

export const linkSelectionToSchedule = async (noteId, payload) => {
  // payload: { start, end, text, date, time?, worker? }
  const response = await api.post(`/notes/${noteId}/schedule`, payload)
  return response.data
}

// cancelJob=false 가 기본 — 이미 잡힌 약속이 글 편집으로 조용히 사라지면 안 된다.
export const unlinkSchedule = async (linkId, cancelJob = false) => {
  const response = await api.delete(
    `/notes/link/${linkId}${cancelJob ? '?cancel_job=1' : ''}`)
  return response.data
}

// 저장 **전에** 부른다 — 저장 뒤 물으면 사용자는 이미 없어진 글을 보며
// 무엇을 지웠는지 기억해내야 한다.
export const checkOrphanedLinks = async (noteId, newBody) => {
  const response = await api.post(`/notes/${noteId}/orphaned`, { note: newBody })
  return response.data
}

export default api
