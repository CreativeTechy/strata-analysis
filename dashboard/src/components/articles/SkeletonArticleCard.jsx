export default function SkeletonArticleCard() {
  return (
    <div className="glass-card article-card article-skeleton" aria-hidden="true">
      <div className="skeleton-row">
        <div className="skeleton-pill skeleton-shimmer" />
        <div className="skeleton-pill skeleton-shimmer" style={{ width: '62%' }} />
      </div>
      <div className="skeleton-title skeleton-shimmer" />
      <div className="skeleton-line skeleton-shimmer" />
      <div className="skeleton-line skeleton-shimmer" style={{ width: '88%' }} />
      <div className="skeleton-tags">
        <div className="skeleton-chip skeleton-shimmer" />
        <div className="skeleton-chip skeleton-shimmer" style={{ width: 92 }} />
      </div>
      <div className="skeleton-footer">
        <div className="skeleton-line skeleton-shimmer" style={{ width: '38%' }} />
        <div className="skeleton-line skeleton-shimmer" style={{ width: '28%' }} />
      </div>
    </div>
  );
}
