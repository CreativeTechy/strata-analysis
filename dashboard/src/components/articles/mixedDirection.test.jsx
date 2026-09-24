import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ArticleCard from './ArticleCard.jsx'
import ArticleRow from './ArticleRow.jsx'

// Covers two of CLAUDE.md's required frontend test scenarios for this
// feature area:
//  (a) an article with mixed Arabic/English title/summary text renders with
//      dir="auto" on those elements, so the browser's bidi algorithm (not a
//      hardcoded ltr/rtl) decides the visible direction of user-authored
//      content regardless of the active interface locale.
//  (b) a sentiment badge shows a translated label while the raw English enum
//      code driving the badge's own CSS/className (and any filter `value=`
//      built from the same code elsewhere, e.g. ArticlesPage's sentiment
//      <select>) is left completely untouched.

const MIXED_ARTICLE = {
  id: 1,
  url: 'https://example.com/a',
  title: 'Battery فشل التوصيل recall announced',
  summary: 'ملخص عن Stellantis وتوصيل البطاريات الجديدة in the region.',
  sentiment: 'negative',
  published: '2026-01-10T00:00:00Z',
  fetched_at: '2026-01-11T00:00:00Z',
  source: 'Example News',
}

describe('mixed-direction article content', () => {
  it('renders the ArticleCard title and summary with dir="auto"', () => {
    render(<ArticleCard article={MIXED_ARTICLE} search="" index={0} isRefreshing={false} onShowDetails={() => {}} />)
    const title = screen.getByRole('heading', { level: 3 })
    expect(title).toHaveAttribute('dir', 'auto')
    const summary = document.querySelector('.article-summary')
    expect(summary).toHaveAttribute('dir', 'auto')
    expect(summary.textContent).toContain('Stellantis')
  })

  it('renders the ArticleRow title and (once expanded) summary with dir="auto"', () => {
    render(
      <ArticleRow
        article={MIXED_ARTICLE}
        search=""
        index={0}
        isExpanded
        isRefreshing={false}
        onToggleExpanded={() => {}}
        onShowDetails={() => {}}
      />
    )
    const title = document.querySelector('.article-row-title')
    expect(title).toHaveAttribute('dir', 'auto')
    const summary = document.querySelector('.article-summary')
    expect(summary).toHaveAttribute('dir', 'auto')
  })
})

describe('translated sentiment label vs. raw enum code', () => {
  it('shows a translated sentiment badge while the sentiment code itself stays untranslated', () => {
    render(<ArticleCard article={MIXED_ARTICLE} search="" index={0} isRefreshing={false} onShowDetails={() => {}} />)
    // The badge's own className is still built directly from the raw,
    // lowercase English enum value (never translated) - this is what
    // filtering/grouping elsewhere keys off.
    const badge = document.querySelector('.badge.negative')
    expect(badge).not.toBeNull()
    // The displayed *label* inside that badge is the translated (English,
    // capitalized) word, not the raw "negative" code.
    expect(badge.textContent).toBe('Negative')
  })
})
