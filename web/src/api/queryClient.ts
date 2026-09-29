import { QueryClient, type DefaultOptions } from '@tanstack/react-query';
import { retryAfterTransientFailure } from './client';

/**
 * The application query policy lives here, not in `main.tsx`, so an acceptance test can never
 * pass against a more forgiving client than the one an analyst's browser actually runs.
 */
export const appQueryDefaults: DefaultOptions = {
  queries: { staleTime: 15_000, retry: retryAfterTransientFailure, refetchOnWindowFocus: false },
  mutations: { retry: false },
};

export function createAppQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: appQueryDefaults });
}
