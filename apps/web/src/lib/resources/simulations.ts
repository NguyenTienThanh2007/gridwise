/**
 * Simulation jobs: `/api/v1/grids/{id}/simulations` and `/api/v1/simulations` (decision
 * 0013). Submitting queues a job and returns at once; a separate worker solves it. The web
 * app follows the job until it ends. Responses never carry tenancy or infrastructure detail.
 */

import { type ApiResult, request } from "@/lib/http/client";
import {
  type Record_,
  decoder,
  int,
  list,
  nullable,
  num,
  oneOf,
  record,
  str,
  timestamp,
  uuid,
} from "@/lib/resources/decode";
import { type Specification, readSpecification } from "@/lib/resources/scenarios";

export const JOB_STATUSES = ["queued", "running", "completed", "failed", "cancelled"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];
export const TERMINAL_STATUSES: readonly JobStatus[] = ["completed", "failed", "cancelled"];
export const OUTCOMES = ["converged", "not_converged"] as const;
export type Outcome = (typeof OUTCOMES)[number];
const SOURCE_STATUSES = ["current", "changed", "deleted"] as const;

export interface Attempt {
  attempt: number;
  startedAt: string;
  endedAt: string | null;
  endedBy: string | null;
}

export interface Job {
  id: string;
  status: JobStatus;
  outcome: Outcome | null;
  attempt: number;
  maxAttempts: number;
  source: {
    gridId: string | null;
    gridVersion: number;
    topologyHash: string;
    status: (typeof SOURCE_STATUSES)[number];
  };
  scenario: { id: string | null; specHash: string; specification: Specification };
  configuration: { algorithm: string; toleranceMva: number; maxIterations: number; hash: string };
  engine: {
    requestedVersion: string;
    executedVersion: string | null;
    solverName: string | null;
    solverVersion: string | null;
    fingerprint: string | null;
  };
  inputSnapshotHash: string;
  failure: { code: string; message: string } | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  cancelledAt: string | null;
  /** Only in a job's own response, not in lists. */
  attempts: Attempt[] | null;
}

export interface JobPage {
  items: Job[];
  total: number;
  limit: number;
  offset: number;
}

const optionalTime = (o: Record_, name: string) => nullable(o, name, timestamp);
const optionalText = (o: Record_, name: string) => nullable(o, name, str);

function readAttempt(value: unknown): Attempt {
  const o = record(value, "attempt");
  return {
    attempt: int(o, "attempt"),
    startedAt: timestamp(o, "started_at"),
    endedAt: optionalTime(o, "ended_at"),
    endedBy: optionalText(o, "ended_by"),
  };
}

function readJob(value: unknown): Job {
  const o = record(value, "job");
  const source = record(o.source, "source");
  const scenario = record(o.scenario, "scenario");
  const configuration = record(o.configuration, "configuration");
  const engine = record(o.engine, "engine");
  const failure =
    o.failure === null || o.failure === undefined ? null : record(o.failure, "failure");
  return {
    id: uuid(o, "id"),
    status: oneOf(o, "status", JOB_STATUSES),
    outcome: nullable(o, "outcome", (obj, name) => oneOf(obj, name, OUTCOMES)),
    attempt: int(o, "attempt"),
    maxAttempts: int(o, "max_attempts"),
    source: {
      gridId: nullable(source, "grid_id", uuid),
      gridVersion: int(source, "grid_version"),
      topologyHash: str(source, "topology_hash"),
      status: oneOf(source, "status", SOURCE_STATUSES),
    },
    scenario: {
      id: nullable(scenario, "id", uuid),
      specHash: str(scenario, "spec_hash"),
      specification: readSpecification(scenario.specification),
    },
    configuration: {
      algorithm: str(configuration, "algorithm"),
      toleranceMva: num(configuration, "tolerance_mva"),
      maxIterations: int(configuration, "max_iterations"),
      hash: str(configuration, "hash"),
    },
    engine: {
      requestedVersion: str(engine, "requested_version"),
      executedVersion: optionalText(engine, "executed_version"),
      solverName: optionalText(engine, "solver_name"),
      solverVersion: optionalText(engine, "solver_version"),
      fingerprint: optionalText(engine, "fingerprint"),
    },
    inputSnapshotHash: str(o, "input_snapshot_hash"),
    failure:
      failure === null ? null : { code: str(failure, "code"), message: str(failure, "message") },
    createdAt: timestamp(o, "created_at"),
    startedAt: optionalTime(o, "started_at"),
    finishedAt: optionalTime(o, "finished_at"),
    cancelledAt: optionalTime(o, "cancelled_at"),
    attempts: o.attempts === undefined ? null : list(o, "attempts", readAttempt),
  };
}

export const decodeJob = decoder(readJob);
export const decodeJobPage = decoder((value): JobPage => {
  const o = record(value, "job list");
  return {
    items: list(o, "items", readJob),
    total: int(o, "total"),
    limit: int(o, "limit"),
    offset: int(o, "offset"),
  };
});

export function isTerminal(status: JobStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export interface JobFilters {
  gridId: string | null;
  status: JobStatus | null;
}

export function fetchJobs(
  { limit, offset, gridId, status }: { limit: number; offset: number } & JobFilters,
  signal?: AbortSignal,
): Promise<ApiResult<JobPage>> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (gridId !== null) query.set("grid_id", gridId);
  if (status !== null) query.set("status", status);
  return request(`/api/v1/simulations?${query}`, decodeJobPage, { signal });
}

export function fetchJob(id: string, signal?: AbortSignal): Promise<ApiResult<Job>> {
  return request(`/api/v1/simulations/${encodeURIComponent(id)}`, decodeJob, { signal });
}

export function cancelJob(id: string): Promise<ApiResult<Job>> {
  return request(`/api/v1/simulations/${encodeURIComponent(id)}/cancel`, decodeJob, {
    method: "POST",
  });
}

export interface SubmissionInput {
  gridId: string;
  /** The grid version on screen, sent as If-Match: the job simulates exactly that version. */
  gridVersion: number;
  scenarioId: string | null;
  configuration: { toleranceMva: number; maxIterations: number } | null;
  /** One per submission form: a retry with the same key never makes a second job. */
  idempotencyKey: string;
}

export function submitSimulation(input: SubmissionInput): Promise<ApiResult<Job>> {
  return request(`/api/v1/grids/${encodeURIComponent(input.gridId)}/simulations`, decodeJob, {
    method: "POST",
    ifMatch: input.gridVersion,
    idempotencyKey: input.idempotencyKey,
    body: {
      ...(input.scenarioId === null ? {} : { scenario_id: input.scenarioId }),
      ...(input.configuration === null
        ? {}
        : {
            configuration: {
              tolerance_mva: input.configuration.toleranceMva,
              max_iterations: input.configuration.maxIterations,
            },
          }),
    },
  });
}

/** The engine's own bounds for the solver options (SimulationConfiguration, PowerFlowOptions). */
export const CONFIGURATION_DEFAULTS = { toleranceMva: 1e-8, maxIterations: 10 } as const;
export const TOLERANCE_MAX = 1e-3;
export const MAX_ITERATIONS_RANGE = [1, 100] as const;
