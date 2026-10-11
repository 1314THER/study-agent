/* Reusable API client. Import from any feature; importing performs no requests.
 * Catalogue IDs (e.g. SET-017) are independent of formal integer pattern IDs.
 */
export function createRoutineMatcher({ baseUrl = '', fetcher = globalThis.fetch } = {}) {
    async function request(path, body, signal) {
        const response = await fetcher(baseUrl.replace(/\/$/, '') + '/routine-matching' + path, {
            method: body === undefined ? 'GET' : 'POST',
            credentials: 'same-origin',
            headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
            signal
        });
        const data = await response.json();
        if (!response.ok) {
            const error = new Error(typeof data.detail === 'string' ? data.detail : '套路匹配请求失败');
            error.status = response.status;
            error.detail = data.detail;
            throw error;
        }
        return data;
    }
    return {
        catalog: ({ signal } = {}) => request('/catalog', undefined, signal),
        retrieve: (question, { signal } = {}) => request('/retrieve', question, signal),
        match: (question, { signal } = {}) => request('/match', question, signal),
        reviews: ({ status = 'pending', offset = 0, limit = 50, signal } = {}) =>
            request('/reviews?' + new URLSearchParams({ status, offset, limit }), undefined, signal),
        decide: (reviewId, decision, { signal } = {}) =>
            request('/reviews/' + encodeURIComponent(reviewId) + '/decision', decision, signal)
    };
}
