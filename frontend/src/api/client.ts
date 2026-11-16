// Thin fetch wrapper. All requests go to the same origin under /api (proxied by Vite in
// development and by nginx in production), so no API URL or credentials live in the bundle.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
    public requestId?: string,
  ) {
    super(message);
  }
}

const BASE = "/api";

async function parse<T>(res: Response): Promise<T> {
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = body?.error;
    throw new ApiError(
      res.status,
      err?.code ?? "http_error",
      err?.message ?? `Request failed with status ${res.status}`,
      err?.details ?? {},
      body?.request_id ?? res.headers.get("x-request-id") ?? undefined,
    );
  }
  return body as T;
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers: opts.body !== undefined ? { "content-type": "application/json" } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "The API could not be reached. Check that the backend is running.");
  }
  return parse<T>(res);
}

export const http = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, { query }),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, { body: body ?? {} }),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, { body }),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, { body }),
  del: <T = void>(path: string) => request<T>("DELETE", path),
};

/** Multipart upload with progress (fetch has no upload progress events). */
export function uploadWithProgress<T>(path: string, form: FormData, onProgress: (ratio: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}${path}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      const res = new Response(xhr.responseText || null, {
        status: xhr.status,
        headers: { "x-request-id": xhr.getResponseHeader("x-request-id") ?? "" },
      });
      parse<T>(res).then(resolve, reject);
    };
    xhr.onerror = () => reject(new ApiError(0, "network_error", "The upload was interrupted. Check your connection."));
    xhr.send(form);
  });
}
