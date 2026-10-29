export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

const DEMO_KEY_STORAGE = 'orion_demo_key';
let inMemoryKey: string | null = null;

export function getDemoKey(): string | null {
  if (inMemoryKey) return inMemoryKey;
  try {
    if (typeof sessionStorage !== 'undefined') {
      return sessionStorage.getItem(DEMO_KEY_STORAGE);
    }
  } catch {
    // Ignore storage access errors
  }
  return null;
}

export function setDemoKey(key: string | null): void {
  inMemoryKey = key;
  try {
    if (typeof sessionStorage !== 'undefined') {
      if (key) {
        sessionStorage.setItem(DEMO_KEY_STORAGE, key);
      } else {
        sessionStorage.removeItem(DEMO_KEY_STORAGE);
      }
    }
  } catch {
    // Ignore storage access errors
  }
}

type UnauthorizedHandler = () => void;
const unauthorizedHandlers = new Set<UnauthorizedHandler>();

export function onUnauthorized(handler: UnauthorizedHandler): () => void {
  unauthorizedHandlers.add(handler);
  return () => {
    unauthorizedHandlers.delete(handler);
  };
}

function triggerUnauthorized(): void {
  unauthorizedHandlers.forEach((handler) => {
    try {
      handler();
    } catch {
      // Ignore listener errors
    }
  });
}

export async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json');
  }

  const demoKey = getDemoKey();
  if (demoKey && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${demoKey}`);
  }

  const response = await fetch(endpoint, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    setDemoKey(null);
    triggerUnauthorized();
  }

  const isJson = response.headers.get('content-type')?.includes('application/json');
  const data = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const errorMessage =
      typeof data === 'object' && data !== null && 'detail' in data
        ? String((data as { detail: unknown }).detail)
        : `HTTP ${response.status}: ${response.statusText}`;
    throw new ApiError(errorMessage, response.status, data);
  }

  return data as T;
}
