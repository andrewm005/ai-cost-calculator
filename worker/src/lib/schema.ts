/**
 * Zod schemas for HTTP request/response shapes — port of app/models.py.
 */

import { z } from 'zod';

// ---------------------------------------------------------------------------
// Enums (mirror Pydantic Literals)
// ---------------------------------------------------------------------------

export const TaskSize = z.enum(['tiny', 'small', 'medium', 'large', 'huge']);
export const ReasoningLevel = z.enum(['low', 'medium', 'high', 'extreme']);
export const TaskType = z.enum(['chat', 'coding', 'writing', 'research', 'agentic']);

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

export const CalculateRequest = z
  .object({
    model_id: z.string().min(1),
    input_tokens: z.number().int().nonnegative().optional(),
    output_tokens: z.number().int().nonnegative().optional(),
    cached_input_tokens: z.number().int().nonnegative().default(0),
    reasoning_tokens: z.number().int().nonnegative().default(0),
    tool_call_count: z.number().int().nonnegative().default(0),
    image_input_count: z.number().int().nonnegative().default(0),
    num_runs: z.number().int().min(1).max(1_000_000).default(1),
    task_size: TaskSize.optional(),
    reasoning_level: ReasoningLevel.default('low'),
    agentic: z.boolean().default(false),
    system_prompt_tokens: z.number().int().nonnegative().default(0),
    task_type: TaskType.default('chat'),
  })
  .strict();

export const CompareRequest = z
  .object({
    model_ids: z.array(z.string().min(1)).min(1).max(10),
    input_tokens: z.number().int().nonnegative().optional(),
    output_tokens: z.number().int().nonnegative().optional(),
    cached_input_tokens: z.number().int().nonnegative().default(0),
    reasoning_tokens: z.number().int().nonnegative().default(0),
    tool_call_count: z.number().int().nonnegative().default(0),
    image_input_count: z.number().int().nonnegative().default(0),
    num_runs: z.number().int().min(1).max(1_000_000).default(1),
    task_size: TaskSize.optional(),
    reasoning_level: ReasoningLevel.default('low'),
    agentic: z.boolean().default(false),
    system_prompt_tokens: z.number().int().nonnegative().default(0),
    task_type: TaskType.default('chat'),
  })
  .strict();

export const LocalCostRequest = z
  .object({
    model_id: z.string().min(1),
    gpu_id: z.string().min(1),
    tokens_per_second: z.number().positive().optional(),
    gpu_cost_per_hour: z.number().nonnegative().default(0.0),
    power_cost_per_kwh: z.number().nonnegative().default(0.0),
    gpu_tdp_watts: z.number().positive().optional(),
    utilization: z.number().positive().lte(1.0).default(1.0),
    input_tokens: z.number().int().nonnegative().optional(),
    output_tokens: z.number().int().nonnegative().optional(),
    task_size: TaskSize.optional(),
    reasoning_level: ReasoningLevel.default('low'),
    task_type: TaskType.default('chat'),
    num_runs: z.number().int().min(1).max(1_000_000).default(1),
  })
  .strict();

// ---------------------------------------------------------------------------
// Inferred TypeScript types
// ---------------------------------------------------------------------------

export type CalculateRequestT = z.infer<typeof CalculateRequest>;
export type CompareRequestT = z.infer<typeof CompareRequest>;
export type LocalCostRequestT = z.infer<typeof LocalCostRequest>;
