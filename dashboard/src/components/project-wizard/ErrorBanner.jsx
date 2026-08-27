export default function ErrorBanner({ message }) {
  if (!message) return null;
  return (
    <div
      style={{
        padding: '12px 14px',
        borderRadius: 14,
        background: 'rgba(255, 71, 87, 0.08)',
        border: '1px solid rgba(255, 71, 87, 0.16)',
        color: '#b42318',
        fontSize: '0.84rem',
        lineHeight: 1.5,
      }}
    >
      {message}
    </div>
  );
}
