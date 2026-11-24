export const FIRESTORE_SAFE_BATCH_LIMIT = 400;

/**
 * Splits a list of write/delete operations into safe Firestore batch chunks
 * well below Firestore's 500-operation hard limit.
 */
export function chunkOperations<T>(
  items: readonly T[],
  maxPerBatch = FIRESTORE_SAFE_BATCH_LIMIT,
): T[][] {
  if (maxPerBatch <= 0 || !Number.isFinite(maxPerBatch)) {
    throw new Error('maxPerBatch must be a positive finite integer.');
  }
  if (items.length === 0) return [];
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += maxPerBatch) {
    chunks.push(items.slice(i, i + maxPerBatch));
  }
  return chunks;
}
