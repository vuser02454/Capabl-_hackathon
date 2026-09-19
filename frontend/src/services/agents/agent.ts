import type { AgentId } from '../../types/agents';

/** Human-readable execution log streamed into the Agent Activity panel. */
export class AgentTrace {
  readonly steps: string[] = [];

  log(message: string) {
    this.steps.push(message);
  }
}

/** Every agent takes a structured input and returns a structured result. */
export interface Agent<TInput, TOutput> {
  readonly id: AgentId;
  readonly name: string;
  run(input: TInput, trace: AgentTrace): Promise<TOutput>;
}
