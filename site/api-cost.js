// Illustrative standard short-context API rates, USD per million tokens, checked 2026-10-27.
// Not a bill: counters do not establish request-level context tiers, cache TTL or service tier.
export const API_PRICES = {
  'gpt-6.1-sol': {input: 2, cached: 0.10, output: 10, provider: 'OpenAI', source: 'https://developers.openai.com/api/docs/pricing'},
  'gpt-6.1-terra': {input: 1, cached: 0.05, output: 5, provider: 'OpenAI', source: 'https://developers.openai.com/api/docs/models/gpt-6.1-terra'},
  'gpt-6-astra': {input: 10, cached: 1, output: 50, provider: 'OpenAI', source: 'https://developers.openai.com/api/docs/pricing'},
  'claude-opus-5-5': {input: 4, cached: 0.20, cacheWrite: 5, output: 20, provider: 'Anthropic', source: 'https://platform.claude.com/docs/en/about-claude/pricing'},
  // Cursor's high is the reasoning level, not the separately priced Grok 4.7 Fast.
  'grok-4.7-high': {input: 2, cached: 0.50, output: 6, provider: 'xAI', source: 'https://docs.x.ai/developers/pricing'},
};
export function estimateApiCost(model, tokens) {
  const rate = API_PRICES[model];
  const {input, cached_input: cached, fresh_input: fresh, output} = tokens || {};
  if (!rate || ![input, cached, fresh, output].every(n => Number.isSafeInteger(n) && n >= 0)
      || cached + fresh !== input) return null;
  const writes = tokens.cache_creation_input;
  if (rate.cacheWrite && writes != null && (!Number.isSafeInteger(writes) || writes < 0 || writes > fresh)) return null;
  const writeCount = rate.cacheWrite && writes != null ? writes : 0;
  return ((fresh - writeCount) * rate.input + writeCount * (rate.cacheWrite || rate.input)
          + cached * rate.cached + output * rate.output) / 1e6;
}
