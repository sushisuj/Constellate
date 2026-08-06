// Thin wrapper around the orchestrator's HTTP API. Every function throws on
// a non-2xx response with the server's own error detail, so callers can
// show it directly rather than a generic "something went wrong."

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8001'

async function unwrap(response) {
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail || detail
    } catch {
      // response wasn't JSON -- fall back to statusText
    }
    throw new Error(detail)
  }
  return response.json()
}

// file: a browser File object (e.g. from an <input type="file"> change event).
// Returns { filename, chunks, topics }.
export async function uploadFile(file) {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    body: form,
  })
  return unwrap(response)
}

// Returns { message, sources, related, backend }.
export async function askQuestion(question) {
  const response = await fetch(`${API_BASE}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  return unwrap(response)
}

// Returns { uploads: [{ filename, chunks, topics }, ...] }.
export async function listUploads() {
  const response = await fetch(`${API_BASE}/uploads`)
  return unwrap(response)
}
