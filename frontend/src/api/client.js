export const API_BASE_URL = 'http://localhost:8000';

async function apiRequest(path, options = {}) {
    const url = `${API_BASE_URL}${path}`;

    const response = await fetch(url, {
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        },
        ...options,
    });

    if (!response.ok) {
        const text = await response.text().catch(() => '');
        throw new Error(`API ${response.status}: ${text || response.statusText}`);
    }

    // if there is no body (204, etc.)
    if (response.status === 204) return null;

    return response.json();
}

export function apiGet(path) {
    return apiRequest(path, { method: 'GET' });
}

export function apiPost(path, body) {
    return apiRequest(path, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}
