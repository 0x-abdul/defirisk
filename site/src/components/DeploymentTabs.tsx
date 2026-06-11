import { useState } from 'preact/hooks';
import styles from './DeploymentTabs.module.css';

export interface DeploymentEntry {
  chain_id: string;
  chain_name: string;
  color: string;
  mark: string;
  tvs_usd: number;
}

interface Props {
  deployments: DeploymentEntry[];
}

function fmtTvs(usd: number): string {
  if (!Number.isFinite(usd) || usd <= 0) return '—';
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(1)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(1)}M`;
  if (usd >= 1e3) return `$${(usd / 1e3).toFixed(0)}K`;
  return `$${usd.toFixed(0)}`;
}

function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

export default function DeploymentTabs({ deployments }: Props) {
  // Default to highest-TVL deployment
  const defaultId = (() => {
    if (deployments.length === 0) return '';
    return deployments.reduce((best, d) =>
      (d.tvs_usd || 0) > (best.tvs_usd || 0) ? d : best,
    ).chain_id;
  })();
  const [active, setActive] = useState(defaultId);
  const activeDeployment = deployments.find((d) => d.chain_id === active);

  if (deployments.length === 0) return null;

  return (
    <div class={styles.deploy} role="tablist" aria-label="Deployments">
      <span class={styles.lbl}>Deployments</span>
      {deployments.map((d) => (
        <button
          type="button"
          key={d.chain_id}
          role="tab"
          aria-selected={active === d.chain_id}
          class={cn(styles.d, active === d.chain_id && styles.on)}
          style={{ background: d.color }}
          title={`${d.chain_name} · ${fmtTvs(d.tvs_usd)}`}
          onClick={() => setActive(d.chain_id)}
          aria-label={`${d.chain_name} deployment, TVS ${fmtTvs(d.tvs_usd)}`}
        >
          <img
            src={`/chains/mono/${d.chain_id}.svg`}
            width="14"
            height="14"
            alt=""
            aria-hidden="true"
            onError={(e) => {
              const img = e.currentTarget as HTMLImageElement;
              img.style.display = 'none';
              const span = img.nextElementSibling as HTMLElement | null;
              if (span) span.style.display = 'inline';
            }}
          />
          <span style={{ display: 'none' }}>{d.mark}</span>
        </button>
      ))}
      {activeDeployment && (
        <span class={styles.tv}>
          {activeDeployment.chain_name} · {fmtTvs(activeDeployment.tvs_usd)}
        </span>
      )}
    </div>
  );
}
