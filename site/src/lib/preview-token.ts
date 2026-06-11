// Comma-separated preview tokens from env.
// During a pre-publication window, share one token per named reviewer.
// Rotate by updating PUBLIC_PRE_PUB_TOKENS and redeploying.
const raw: string = (import.meta.env.PUBLIC_PRE_PUB_TOKENS as string | undefined) ?? '';
export const PRE_PUB_TOKENS: readonly string[] = raw
  .split(',')
  .map((t) => t.trim())
  .filter(Boolean);
