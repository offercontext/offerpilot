interface Props {
  /** Each axis maps [label] → [0..100] score. 5 axes is the canonical layout. */
  axes: { label: string; value: number }[];
  size?: number;
}

/**
 * Dependency-free radar/spider chart, hand-drawn in SVG.
 * Uses --op-* tokens via currentColor for stroke so it adapts to dark mode.
 * Per ui-ux-pro-max radar guidance: single dataset fill at ~20% brand color,
 * with the score table rendered alongside it by the parent for a11y.
 */
export default function RadarChart({ axes, size = 240 }: Props) {
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 38;
  const n = axes.length;
  const angle = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2;

  // Grid rings at 25/50/75/100%.
  const rings = [0.25, 0.5, 0.75, 1];
  const ringPaths = rings.map((ring) => {
    const pts = axes.map((_, i) => {
      const a = angle(i);
      const x = cx + Math.cos(a) * radius * ring;
      const y = cy + Math.sin(a) * radius * ring;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    return `M${pts.join(' L')} Z`;
  });

  const scorePoints = axes.map((ax, i) => {
    const a = angle(i);
    const r = (Math.max(0, Math.min(100, ax.value)) / 100) * radius;
    const x = cx + Math.cos(a) * r;
    const y = cy + Math.sin(a) * r;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const scorePath = `M${scorePoints.join(' L')} Z`;

  const labelPoints = axes.map((ax, i) => {
    const a = angle(i);
    const x = cx + Math.cos(a) * (radius + 18);
    const y = cy + Math.sin(a) * (radius + 18);
    const anchor =
      Math.abs(Math.cos(a)) < 0.2 ? 'middle' : Math.cos(a) > 0 ? 'start' : 'end';
    return { x, y, label: ax.label, anchor };
  });

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="面试评分雷达图">
      <g fill="none" stroke="var(--op-border)" strokeWidth={1}>
        {ringPaths.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
      {/* Axis spokes */}
      <g stroke="var(--op-border)" strokeWidth={1}>
        {axes.map((_, i) => {
          const a = angle(i);
          const x = cx + Math.cos(a) * radius;
          const y = cy + Math.sin(a) * radius;
          return <line key={i} x1={cx} y1={cy} x2={x} y2={y} />;
        })}
      </g>
      {/* Score polygon */}
      <path
        d={scorePath}
        fill="var(--op-primary)"
        fillOpacity={0.18}
        stroke="var(--op-primary)"
        strokeWidth={2}
        strokeLinejoin="round"
      />
      {/* Score vertices */}
      <g fill="var(--op-primary)">
        {axes.map((_, i) => {
          const a = angle(i);
          const r = (Math.max(0, Math.min(100, axes[i].value)) / 100) * radius;
          return <circle key={i} cx={cx + Math.cos(a) * r} cy={cy + Math.sin(a) * r} r={3} />;
        })}
      </g>
      {/* Labels */}
      <g fill="var(--op-muted-strong)" fontSize={11} fontWeight={600}>
        {labelPoints.map((p, i) => (
          <text
            key={i}
            x={p.x}
            y={p.y}
            textAnchor={p.anchor as 'middle' | 'start' | 'end'}
            dominantBaseline="middle"
          >
            {p.label}
          </text>
        ))}
      </g>
    </svg>
  );
}