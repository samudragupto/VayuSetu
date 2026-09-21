export interface RetryOptions {
  attempts?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  shouldRetry?: (error: unknown) => boolean;
  onRetry?: (error: unknown, attempt: number, delayMs: number) => void;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Extract an HTTP status code from common error shapes (fetch, gaxios, twilio). */
export function errorStatus(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null) {
    return undefined;
  }
  const candidate = error as { status?: unknown; code?: unknown; statusCode?: unknown; response?: { status?: unknown } };
  for (const value of [candidate.status, candidate.statusCode, candidate.code, candidate.response?.status]) {
    if (typeof value === "number" && value >= 100 && value <= 599) {
      return value;
    }
  }
  return undefined;
}

/** Retry on rate limiting, server errors and network failures only. */
export function isTransientError(error: unknown): boolean {
  const status = errorStatus(error);
  if (status !== undefined) {
    return status === 408 || status === 425 || status === 429 || status >= 500;
  }
  const code = (error as { code?: string })?.code;
  return ["ECONNRESET", "ETIMEDOUT", "EAI_AGAIN", "ECONNREFUSED", "EPIPE", "UND_ERR_SOCKET", "UND_ERR_CONNECT_TIMEOUT"].includes(String(code));
}

/**
 * Execute `operation` with exponential backoff and full jitter.
 * Defaults: 4 attempts, 300 ms base delay, 5 s cap.
 */
export async function withRetry<T>(operation: (attempt: number) => Promise<T>, options: RetryOptions = {}): Promise<T> {
  const attempts = options.attempts ?? 4;
  const baseDelayMs = options.baseDelayMs ?? 300;
  const maxDelayMs = options.maxDelayMs ?? 5000;
  const shouldRetry = options.shouldRetry ?? isTransientError;

  let lastError: unknown;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await operation(attempt);
    } catch (error) {
      lastError = error;
      if (attempt === attempts || !shouldRetry(error)) {
        throw error;
      }
      const exponential = Math.min(maxDelayMs, baseDelayMs * 2 ** (attempt - 1));
      const delayMs = Math.round(Math.random() * exponential);
      options.onRetry?.(error, attempt, delayMs);
      await sleep(delayMs);
    }
  }
  throw lastError;
}
