function ownedUrl(value, origins) {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' && !url.username && !url.password && origins.includes(url.origin);
  } catch { return false; }
}

function validateHandoff(payload, editorOrigin) {
  if (!payload || typeof payload.url !== 'string' || !ownedUrl(payload.url, [editorOrigin])) return false;
  const url = new URL(payload.url);
  return typeof payload.handoff_id === 'string' && /^[a-f0-9-]{36}$/.test(payload.handoff_id)
    && typeof payload.state === 'string' && payload.state.length > 0 && payload.state.length < 512
    && typeof payload.confirmation_token === 'string' && payload.confirmation_token.length > 0 && payload.confirmation_token.length < 4096
    && url.searchParams.get('handoff_id') === payload.handoff_id
    && url.searchParams.get('state') === payload.state;
}
module.exports = { ownedUrl, validateHandoff };
