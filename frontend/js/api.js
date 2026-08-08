//módulo: api — cliente HTTP hacia /api/*

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const body = isJson ? await res.json() : null;
  if (!res.ok) {
    const detail = body && body.detail ? body.detail : res.statusText;
    const message = Array.isArray(detail) ? detail.join("\n") : String(detail);
    throw new Error(message);
  }
  return body;
}


export { api };
