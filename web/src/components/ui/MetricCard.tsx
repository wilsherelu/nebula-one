interface Props {
  label: string;
  value: string;
  unit?: string;
  delta?: string;
  tone?: 'neutral' | 'positive' | 'negative';
}

export function MetricCard({ label, value, unit, delta, tone = 'neutral' }: Props) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <div className="metric-card__label">{label}</div>
      <div className="metric-card__value tabular">{value}</div>
      <div className="metric-card__foot">
        <span>{unit}</span>
        {delta ? <span className="metric-card__delta">{delta}</span> : null}
      </div>
    </article>
  );
}
