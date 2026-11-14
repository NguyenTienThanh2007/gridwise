/**
 * Small building blocks for hand-written decoders (decision 0014, D1).
 *
 * A decoder reads an untrusted payload field by field. Any field of the wrong type throws
 * `DecodeError`, and `decoder(...)` turns that into `null`: the caller sees one failure,
 * never a partly decoded object. Numbers must be finite; `null` is accepted only where a
 * reader says so, because a missing value is never the same as zero.
 */

import type { Decoder } from "@/lib/http/client";

export class DecodeError extends Error {}

export type Record_ = Record<string, unknown>;

export function record(value: unknown, where = "value"): Record_ {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new DecodeError(`${where} is not an object`);
  }
  return value as Record_;
}

export function str(object: Record_, name: string): string {
  const value = object[name];
  if (typeof value !== "string") throw new DecodeError(`${name} is not a string`);
  return value;
}

export function num(object: Record_, name: string): number {
  const value = object[name];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new DecodeError(`${name} is not a finite number`);
  }
  return value;
}

export function int(object: Record_, name: string): number {
  const value = num(object, name);
  if (!Number.isInteger(value)) throw new DecodeError(`${name} is not an integer`);
  return value;
}

export function bool(object: Record_, name: string): boolean {
  const value = object[name];
  if (typeof value !== "boolean") throw new DecodeError(`${name} is not a boolean`);
  return value;
}

export function oneOf<T extends string>(object: Record_, name: string, allowed: readonly T[]): T {
  const value = str(object, name);
  const found = allowed.find((candidate) => candidate === value);
  if (found === undefined) throw new DecodeError(`${name} is not one of ${allowed.join(", ")}`);
  return found;
}

/** A field that may be `null` (or absent): `read` decides what a present value must be. */
export function nullable<T>(
  object: Record_,
  name: string,
  read: (object: Record_, name: string) => T,
): T | null {
  return object[name] === null || object[name] === undefined ? null : read(object, name);
}

export function list<T>(object: Record_, name: string, item: (value: unknown) => T): T[] {
  const value = object[name];
  if (!Array.isArray(value)) throw new DecodeError(`${name} is not a list`);
  return value.map(item);
}

/** An ISO 8601 timestamp, kept as the API's text (it carries the time zone). */
export function timestamp(object: Record_, name: string): string {
  const value = str(object, name);
  if (Number.isNaN(Date.parse(value))) throw new DecodeError(`${name} is not a timestamp`);
  return value;
}

export function decoder<T>(read: (value: unknown) => T): Decoder<T> {
  return (value) => {
    try {
      return read(value);
    } catch (error) {
      if (error instanceof DecodeError) return null;
      throw error;
    }
  };
}

export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}

export function uuid(object: Record_, name: string): string {
  const value = str(object, name);
  if (!isUuid(value)) throw new DecodeError(`${name} is not a UUID`);
  return value;
}
