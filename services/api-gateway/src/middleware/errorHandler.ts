import type { NextFunction, Request, Response } from "express";

import type { Logger } from "../logger";

export class HttpError extends Error {
  constructor(public readonly status: number, message: string, public readonly details?: unknown) {
    super(message);
    this.name = "HttpError";
  }
}

export function notFoundHandler(req: Request, res: Response): void {
  res.status(404).json({ error: "not found", path: req.path });
}

export function errorHandler(logger: Logger) {
  // Express identifies error middleware by arity, so `next` must stay declared.
  return (error: unknown, req: Request, res: Response, _next: NextFunction): void => {
    if (error instanceof HttpError) {
      res.status(error.status).json({ error: error.message, details: error.details });
      return;
    }
    const status = typeof (error as { status?: unknown })?.status === "number" ? (error as { status: number }).status : 500;
    if (status >= 500) {
      logger.error({ err: error, path: req.path }, "Unhandled error");
    }
    res.status(status).json({ error: status >= 500 ? "internal error" : (error as Error).message });
  };
}
