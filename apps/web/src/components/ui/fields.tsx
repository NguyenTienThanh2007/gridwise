"use client";

import { type ReactNode, useId } from "react";

/**
 * Labelled form fields. The description and the error are tied to the control with
 * `aria-describedby`; an error also sets `aria-invalid`.
 */

function Help({
  id,
  description,
  error,
}: {
  id: string;
  description?: ReactNode;
  error?: string | null;
}) {
  return (
    <>
      {description === undefined ? null : (
        <p id={`${id}-description`} className="mt-1 text-xs text-muted">
          {description}
        </p>
      )}
      {error === null || error === undefined ? null : (
        <p id={`${id}-error`} className="mt-1 text-xs font-medium text-bad">
          {error}
        </p>
      )}
    </>
  );
}

function describedBy(id: string, description: unknown, error: string | null | undefined) {
  const ids = [
    description === undefined ? null : `${id}-description`,
    error === null || error === undefined ? null : `${id}-error`,
  ].filter((value) => value !== null);
  return ids.length === 0 ? undefined : ids.join(" ");
}

const CONTROL = "mt-1 w-full rounded border px-2 py-1.5 text-sm";

interface TextProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  description?: ReactNode;
  error?: string | null;
  /** Shown as a count; the limit itself is checked by the form. */
  maxLength?: number;
}

export function TextField({ label, value, onChange, description, error, maxLength }: TextProps) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, description, error)}
        className={`${CONTROL} ${error ? "border-bad" : "border-line"}`}
      />
      {maxLength === undefined ? null : (
        <p className="mt-1 text-right text-xs tabular-nums text-muted">
          {value.length} / {maxLength}
        </p>
      )}
      <Help id={id} description={description} error={error} />
    </div>
  );
}

export function TextArea({ label, value, onChange, description, error, maxLength }: TextProps) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        value={value}
        rows={4}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, description, error)}
        className={`${CONTROL} ${error ? "border-bad" : "border-line"}`}
      />
      {maxLength === undefined ? null : (
        <p className="mt-1 text-right text-xs tabular-nums text-muted">
          {value.length} / {maxLength}
        </p>
      )}
      <Help id={id} description={description} error={error} />
    </div>
  );
}

export interface Option<T extends string> {
  value: T;
  label: string;
}

export function RadioGroup<T extends string>({
  legend,
  options,
  value,
  onChange,
  description,
}: {
  legend: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  description?: ReactNode;
}) {
  const id = useId();
  return (
    <fieldset aria-describedby={describedBy(id, description, null)}>
      <legend className="text-sm font-medium">{legend}</legend>
      <div className="mt-1 flex flex-wrap gap-4">
        {options.map((option) => (
          <label key={option.value} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={id}
              value={option.value}
              checked={option.value === value}
              onChange={() => onChange(option.value)}
            />
            {option.label}
          </label>
        ))}
      </div>
      <Help id={id} description={description} />
    </fieldset>
  );
}

export function Select<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-muted">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => {
          const chosen = options.find((option) => option.value === event.target.value);
          if (chosen !== undefined) onChange(chosen.value);
        }}
        className="mt-1 rounded border border-line bg-panel px-2 py-1.5 text-sm"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
