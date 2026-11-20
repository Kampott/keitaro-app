/**
 * Общий fetch-клиент. backend отдаёт ошибки в формате {code, message, details?}
 * (ТЗ §8); ключ Keitaro и Basic-пароль здесь не сохраняются на диск.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let basicAuth: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setBasicAuth(username: string, password: string): void {
  const bytes = new TextEncoder().encode(`${username}:${password}`);
  let binary = "";
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  basicAuth = `Basic ${btoa(binary)}`;
}

export function registerUnauthorized(handler: () => void): void {
  onUnauthorized = handler;
}

export function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (basicAuth) headers.set("Authorization", basicAuth);

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "NETWORK", "backend недоступен");
  }

  if (response.status === 401) {
    onUnauthorized?.();
    throw new ApiError(401, "UNAUTHORIZED", "Нужен логин и пароль");
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = body && typeof body === "object" ? (body as Record<string, unknown>) : {};
    const code = typeof error.code === "string" ? error.code : `HTTP_${response.status}`;
    const message = typeof error.message === "string" ? error.message : `Ошибка ${response.status}`;
    throw new ApiError(response.status, code, message, error.details);
  }
  return body as T;
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.code === "NETWORK" ? error.message : `${error.code}: ${error.message}`;
  }
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}
