import { timingSafeEqual } from "node:crypto";
import type { NextFunction, Request, Response } from "express";

function tokensMatch(received: string, expected: string): boolean {
  const receivedBuffer = Buffer.from(received);
  const expectedBuffer = Buffer.from(expected);
  return (
    receivedBuffer.length === expectedBuffer.length &&
    timingSafeEqual(receivedBuffer, expectedBuffer)
  );
}

export function requireSignalToken(
  req: Request,
  res: Response,
  next: NextFunction,
): void {
  res.setHeader("Cache-Control", "private, no-store");
  res.setHeader("Vary", "Authorization");

  const expected = process.env["SIGNAL_API_TOKEN"];
  if (!expected) {
    res.status(503).json({ error: "Signal API is not configured." });
    return;
  }

  const authorization = req.get("authorization");
  const prefix = "Bearer ";
  const received =
    authorization?.startsWith(prefix) === true
      ? authorization.slice(prefix.length)
      : "";
  if (!received || !tokensMatch(received, expected)) {
    res.status(401).json({ error: "Unauthorized." });
    return;
  }
  next();
}