/**
 * Cloudflare Worker: serves the dashboard (static assets) and relays the
 * "Run Extractor" button to the GitHub Actions pipeline.
 *
 * Why: Workers can't run the Python/Scrapy backend, but they can trigger the
 * free GitHub Actions workflow that already does scrape -> enrich -> save.
 * The GitHub token lives only as a Worker secret, never in the browser.
 *
 * Secrets / vars (see wrangler.toml + `wrangler secret put`):
 *   GITHUB_TOKEN    (secret)  fine-grained PAT with Actions: read & write
 *   DEEPSEEK_API_KEY (secret) for the Intelligence Copilot chat
 *   GH_OWNER, GH_REPO, GH_WORKFLOW, GH_REF  (vars)
 */

const COPILOT_SYSTEM_PROMPT = `You are Strata Intelligence Copilot, an analyst for article sets. You receive scraped items with fields such as title, source, sentiment, category, summary, and optional entity/topic metadata. Answer using ONLY these items, and never contradict the stated article count.

DEFAULT: keep it short and high-signal - a scannable overview, ~120-180 words. For a general question ("what's the analysis", "anything in common", "what's the sentiment"), reply with:
- **Takeaway:** one punchy sentence on the overall picture.
- **Mood:** the rough sentiment split (positive / negative / neutral) and the general tone.
- **Concerns:** 1-2 sentences on what the negative or cautionary coverage is about.
- **Upsides:** 1-2 sentences on what the positive or promising coverage is about.
- **Common threads:** 1-3 short bullets of recurring themes; if there's no clear pattern, say what stands out instead.
Use light Markdown (bold labels, a few short bullets). Do NOT list every article, do NOT cite "Article N", and do NOT open with "Based on the N articles".

DEEP DIVE: only when the user explicitly asks to go deeper / expand / give details / draft a full report - then give the longer structured breakdown with evidence and concrete examples from the articles.

Always format with clean Markdown.`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Button press -> kick off the GitHub Actions pipeline.
    if (request.method === 'POST' && url.pathname === '/scrape') {
      return triggerWorkflow(env);
    }

    // Intelligence Copilot -> DeepSeek chat over the filtered articles.
    if (request.method === 'POST' && url.pathname === '/api/chat') {
      return handleChat(request, env);
    }

    // Any other /api/* path: return JSON 404 (don't fall back to index.html).
    if (url.pathname.startsWith('/api/')) {
      return Response.json({ error: 'Not found' }, { status: 404 });
    }

    // Everything else: serve the built dashboard.
    return env.ASSETS.fetch(request);
  },
};

async function handleChat(request, env) {
  if (!env.DEEPSEEK_API_KEY) {
    return Response.json(
      { error: 'DEEPSEEK_API_KEY not configured on the Worker' },
      { status: 500 },
    );
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const question = String(body.question || '').slice(0, 2000);
  const articles = Array.isArray(body.articles) ? body.articles.slice(0, 80) : [];
  const total = Number(body.total) || articles.length;

  if (!question.trim()) {
    return Response.json({ error: 'Empty question' }, { status: 400 });
  }

  const context = articles
    .map((a, i) =>
      `${i + 1}. [${a.source || '?'} | ${a.sentiment || 'neutral'} | ${a.category || 'other'}` +
      ` | score ${a.relevance_score ?? '?'}] ${a.title || ''}\n   ${a.summary || ''}`)
    .join('\n');

  const systemPrompt = COPILOT_SYSTEM_PROMPT;
  const userPrompt =
    `There are ${total} articles in the current view.\n\n` +
    `${context || '(none selected)'}\n\nQuestion: ${question}`;

  const resp = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'deepseek-chat',
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt },
      ],
      temperature: 0.3,
      max_tokens: 700,
    }),
  });

  if (!resp.ok) {
    const detail = await resp.text();
    return Response.json(
      { error: 'DeepSeek request failed', status: resp.status, detail },
      { status: 502 },
    );
  }

  const data = await resp.json();
  const reply = data?.choices?.[0]?.message?.content?.trim() || 'No response.';
  return Response.json({ reply });
}

async function triggerWorkflow(env) {
  if (!env.GITHUB_TOKEN) {
    return Response.json(
      { error: 'GITHUB_TOKEN not configured on the Worker' },
      { status: 500 },
    );
  }

  const endpoint =
    `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}` +
    `/actions/workflows/${env.GH_WORKFLOW}/dispatches`;

  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'strata-media-worker',
    },
    body: JSON.stringify({ ref: env.GH_REF || 'main' }),
  });

  // GitHub returns 204 No Content on success.
  if (resp.status === 204) {
    return Response.json({
      message: 'Scrape triggered via GitHub Actions. New data lands in ~3 min.',
    });
  }

  const detail = await resp.text();
  return Response.json(
    { error: 'Failed to trigger workflow', status: resp.status, detail },
    { status: 502 },
  );
}
