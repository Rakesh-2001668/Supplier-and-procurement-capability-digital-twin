'use client';

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, Paged } from './api';
import { useToast } from '@/components/pic/toast';

/** GET a resource; pass null to skip. */
export function useApi<T>(path: string | null, options: { refetchInterval?: number } = {}) {
  return useQuery<T, ApiError>({
    queryKey: [path],
    queryFn: () => api.get<T>(path as string),
    enabled: !!path,
    refetchInterval: options.refetchInterval,
    retry: (count, error) => count < 2 && (error as ApiError).status >= 500,
  });
}

/** Cursor-paginated worklist with "load more". */
export function useList<T>(path: string) {
  const query = useInfiniteQuery<Paged<T>, ApiError>({
    queryKey: [path, 'list'],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const sep = path.includes('?') ? '&' : '?';
      return api.get<Paged<T>>(pageParam ? `${path}${sep}cursor=${encodeURIComponent(String(pageParam))}` : path);
    },
    getNextPageParam: (last) => last.nextCursor,
  });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  return { ...query, items };
}

/**
 * Run a command (POST/PATCH). On success every query is refreshed so worklists, object pages
 * and the process tab show the new state; errors are shown as problem+json toasts.
 */
export function useCommand<TArgs = void, TResult = unknown>(
  run: (args: TArgs) => Promise<TResult>,
  options: { success?: string | ((result: TResult) => string); onSuccess?: (result: TResult) => void } = {},
) {
  const client = useQueryClient();
  const toast = useToast();
  return useMutation<TResult, ApiError, TArgs>({
    mutationFn: run,
    onSuccess: async (result) => {
      await client.invalidateQueries();
      if (options.success) toast.success(typeof options.success === 'function' ? options.success(result) : options.success);
      options.onSuccess?.(result);
    },
    onError: (error) => toast.problem(error),
  });
}
