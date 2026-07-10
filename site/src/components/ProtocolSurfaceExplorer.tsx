import { useEffect, useMemo, useState } from 'preact/hooks';
import styles from './ProtocolSurfaceExplorer.module.css';

type ScoreLight = 'red' | 'yellow' | 'green' | 'gray' | 'not_assessed' | 'not_applicable';

interface FactorMeta {
  id: string;
  name: string;
  category_id: number;
  is_critical?: boolean;
}

interface CategoryMeta {
  id: number;
  name: string;
  short?: string;
}

interface ScoreEntry {
  factor_id?: string;
  score?: ScoreLight;
  evidence_summary?: string;
  gap_reason?: string | null;
}

interface DeploymentEntry {
  id?: string;
  chain?: string;
  display_name?: string | null;
  tvs_usd?: number | string | null;
  deployment_key?: string | null;
}

interface SurfaceEntry {
  surface_id?: string | null;
  surface_slug?: string;
  display_name?: string;
  status?: string;
  tvs_usd?: number | string | null;
  headline_grade?: string | null;
  risk_score?: number | string | null;
  graded_at?: string | null;
  scope_note?: string | null;
  legacy_slug?: string | null;
  is_primary?: boolean;
  category_severities?: Record<string, number> | null;
  cap_applied?: string | null;
  cap_reason?: string | null;
  deployments?: DeploymentEntry[];
  factor_scores?: ScoreEntry[];
  deployment_factor_scores?: Record<string, ScoreEntry[]>;
  deployment_category_severities?: Record<string, Record<string, number>>;
}

interface Props {
  familySlug: string;
  surfaces: SurfaceEntry[];
  categories: CategoryMeta[];
  factors: FactorMeta[];
  reviewMode?: boolean;
  legacyCaveat?: string | null;
}

const SCORE_ORDER: Record<string, number> = {
  red: 0,
  yellow: 1,
  gray: 2,
  not_assessed: 2,
  not_applicable: 2,
  green: 3,
};

function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

function numberValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function fmtUsd(value: unknown): string {
  const usd = numberValue(value);
  if (usd === null || usd <= 0) return '-';
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(1)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(1)}M`;
  if (usd >= 1e3) return `$${(usd / 1e3).toFixed(0)}K`;
  return `$${usd.toFixed(0)}`;
}

function fmtDate(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function lightFromSeverity(value: number | undefined): 'red' | 'yellow' | 'green' | 'gray' {
  if (value === undefined) return 'gray';
  if (value >= 50) return 'red';
  if (value >= 20) return 'yellow';
  return 'green';
}

function severityFromCounts(
  counts: { red: number; yellow: number; green: number } | undefined
): number | undefined {
  if (!counts) return undefined;
  const denominator = counts.red + counts.yellow + counts.green;
  if (denominator === 0) return undefined;
  return ((counts.red * 3 + counts.yellow) / (denominator * 3)) * 100;
}

function statusLabel(status?: string): string {
  if (!status) return 'active';
  return status.replace(/_/g, ' ');
}

export default function ProtocolSurfaceExplorer({
  familySlug,
  surfaces,
  categories,
  factors,
  reviewMode = false,
  legacyCaveat,
}: Props) {
  const factorById = useMemo(
    () => new Map(factors.map((factor) => [factor.id, factor])),
    [factors]
  );
  const defaultSurface: SurfaceEntry = surfaces.find((surface) => surface.is_primary) ??
    surfaces[0] ?? { surface_slug: 'default' };
  const defaultSurfaceSlug =
    surfaces.length > 1 ? '__overview' : (defaultSurface.surface_slug ?? 'default');
  const [activeSurfaceSlug, setActiveSurfaceSlug] = useState(defaultSurfaceSlug);
  const activeSurface =
    surfaces.find((surface) => surface.surface_slug === activeSurfaceSlug) ?? defaultSurface;
  const deployments = activeSurface.deployments ?? [];
  const [activeDeploymentId, setActiveDeploymentId] = useState<string>('');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedSurface = params.get('surface');
    if (requestedSurface && surfaces.some((surface) => surface.surface_slug === requestedSurface)) {
      setActiveSurfaceSlug(requestedSurface);
    }
  }, [surfaces]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedDeployment = params.get('deployment');
    const requestedChain = params.get('chain');
    const matchingDeployment =
      deployments.find((deployment) => deployment.id === requestedDeployment) ??
      deployments.find((deployment) => deployment.chain === requestedChain);
    setActiveDeploymentId(matchingDeployment?.id ?? '');
  }, [activeSurfaceSlug, deployments]);

  function updateUrl(surfaceSlug: string, deploymentId = '') {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    if (surfaceSlug === '__overview') params.delete('surface');
    else params.set('surface', surfaceSlug);
    const deployment = deployments.find((entry) => entry.id === deploymentId);
    if (surfaceSlug !== '__overview' && deployment?.id) {
      params.set('deployment', deployment.id);
      if (deployment.chain) params.set('chain', deployment.chain);
      else params.delete('chain');
    } else {
      params.delete('deployment');
      params.delete('chain');
    }
    const query = params.toString();
    const next = query ? `${window.location.pathname}?${query}` : window.location.pathname;
    window.history.replaceState({}, '', next);
  }

  function selectSurface(surfaceSlug: string) {
    setActiveSurfaceSlug(surfaceSlug);
    setActiveDeploymentId('');
    updateUrl(surfaceSlug);
  }

  function selectDeployment(deploymentId: string) {
    setActiveDeploymentId(deploymentId);
    updateUrl(activeSurface.surface_slug ?? 'default', deploymentId);
  }

  const activeScores = useMemo(() => {
    const deploymentScores =
      activeDeploymentId && activeSurface.deployment_factor_scores
        ? activeSurface.deployment_factor_scores[activeDeploymentId]
        : null;
    return deploymentScores ?? activeSurface.factor_scores ?? [];
  }, [activeDeploymentId, activeSurface]);

  const scoreRows = useMemo(() => {
    return activeScores
      .flatMap((score) => {
        const factorId = score.factor_id ?? '';
        const factor = factorById.get(factorId);
        if (!factor) return [];
        return [
          {
            factorId,
            factorName: factor.name,
            categoryId: factor.category_id,
            critical: Boolean(factor.is_critical),
            score: score.score ?? 'gray',
            evidence: score.evidence_summary ?? '',
            gapReason: score.gap_reason ?? null,
          },
        ];
      })
      .sort((a, b) => {
        const scoreDelta = (SCORE_ORDER[a.score] ?? 4) - (SCORE_ORDER[b.score] ?? 4);
        return scoreDelta || a.factorId.localeCompare(b.factorId);
      });
  }, [activeScores, factorById]);

  const rollup = useMemo(() => {
    const result = new Map<
      number,
      { red: number; yellow: number; green: number; gray: number; total: number }
    >();
    for (const category of categories) {
      result.set(category.id, { red: 0, yellow: 0, green: 0, gray: 0, total: 0 });
    }
    for (const row of scoreRows) {
      const counts = result.get(row.categoryId);
      if (!counts) continue;
      counts.total += 1;
      if (row.score === 'red') counts.red += 1;
      else if (row.score === 'yellow') counts.yellow += 1;
      else if (row.score === 'green') counts.green += 1;
      else counts.gray += 1;
    }
    return result;
  }, [categories, scoreRows]);

  const selectedDeployment = deployments.find((deployment) => deployment.id === activeDeploymentId);
  const redCount = scoreRows.filter((row) => row.score === 'red').length;
  const yellowCount = scoreRows.filter((row) => row.score === 'yellow').length;
  const greenCount = scoreRows.filter((row) => row.score === 'green').length;

  return (
    <div class={styles.shell}>
      <div class={styles.tabs} role="tablist" aria-label="Protocol surfaces">
        <button
          type="button"
          class={cn(styles.tab, activeSurfaceSlug === '__overview' && styles.active)}
          role="tab"
          aria-selected={activeSurfaceSlug === '__overview'}
          onClick={() => selectSurface('__overview')}
        >
          Overview
        </button>
        {surfaces.map((surface) => {
          const surfaceSlug = surface.surface_slug ?? 'default';
          return (
            <button
              key={surfaceSlug}
              type="button"
              class={cn(styles.tab, activeSurfaceSlug === surfaceSlug && styles.active)}
              role="tab"
              aria-selected={activeSurfaceSlug === surfaceSlug}
              onClick={() => selectSurface(surfaceSlug)}
            >
              {surface.display_name ?? surfaceSlug}
            </button>
          );
        })}
      </div>

      {activeSurfaceSlug === '__overview' ? (
        <section class={styles.section}>
          <div class={styles.sectionHead}>
            <span class={styles.num}>01</span>
            <h2>Version overview</h2>
          </div>
          {legacyCaveat && <p class={styles.caveat}>{legacyCaveat}</p>}
          <div class={styles.tableWrap}>
            <table class={styles.compare}>
              <thead>
                <tr>
                  <th>Surface</th>
                  <th>Status</th>
                  <th>TVS</th>
                  <th>Grade</th>
                  <th>Risk</th>
                  <th>Last assessed</th>
                  <th>Scope</th>
                </tr>
              </thead>
              <tbody>
                {surfaces.map((surface) => (
                  <tr key={surface.surface_slug}>
                    <td>
                      <button
                        type="button"
                        class={styles.linkButton}
                        onClick={() => selectSurface(surface.surface_slug ?? 'default')}
                      >
                        {surface.display_name ?? surface.surface_slug}
                      </button>
                    </td>
                    <td>
                      <span class={styles.status}>{statusLabel(surface.status)}</span>
                    </td>
                    <td>{fmtUsd(surface.tvs_usd)}</td>
                    <td>
                      <span class={styles.grade}>{surface.headline_grade ?? '-'}</span>
                    </td>
                    <td>{numberValue(surface.risk_score)?.toFixed(1) ?? '-'}</td>
                    <td>{fmtDate(surface.graded_at)}</td>
                    <td>{surface.scope_note ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <>
          <section class={styles.section}>
            <div class={styles.surfaceHead}>
              <div>
                <span class={styles.num}>01</span>
                <h2>{activeSurface.display_name ?? activeSurface.surface_slug}</h2>
                <p>
                  {statusLabel(activeSurface.status)}
                  {selectedDeployment?.chain ? ` / ${selectedDeployment.chain}` : ''}
                  {activeSurface.scope_note ? ` / ${activeSurface.scope_note}` : ''}
                </p>
              </div>
              <div class={styles.gradeBox}>
                <span>{activeSurface.headline_grade ?? '-'}</span>
                <b>{numberValue(activeSurface.risk_score)?.toFixed(1) ?? '-'}</b>
              </div>
            </div>

            {deployments.length > 0 && (
              <div class={styles.chainSelector} role="tablist" aria-label="Chain deployments">
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeDeploymentId === ''}
                  class={cn(styles.chainButton, activeDeploymentId === '' && styles.chainActive)}
                  onClick={() => selectDeployment('')}
                >
                  Surface
                </button>
                {deployments.map((deployment) => (
                  <button
                    key={deployment.id}
                    type="button"
                    role="tab"
                    aria-selected={activeDeploymentId === deployment.id}
                    class={cn(
                      styles.chainButton,
                      activeDeploymentId === deployment.id && styles.chainActive
                    )}
                    onClick={() => selectDeployment(deployment.id ?? '')}
                  >
                    {deployment.display_name ||
                      deployment.chain ||
                      deployment.deployment_key ||
                      'Chain'}
                  </button>
                ))}
              </div>
            )}

            <div class={styles.metrics}>
              <span>
                <b>{fmtUsd(activeSurface.tvs_usd)}</b> TVS
              </span>
              <span>
                <b>{fmtDate(activeSurface.graded_at)}</b> assessed
              </span>
              <span>
                <b>
                  {redCount} / {yellowCount} / {greenCount}
                </b>{' '}
                R/Y/G
              </span>
            </div>
          </section>

          <section class={styles.section}>
            <div class={styles.sectionHead}>
              <span class={styles.num}>02</span>
              <h2>Risk profile</h2>
              <span>{scoreRows.length} factors</span>
            </div>
            <div class={styles.categoryGrid}>
              {categories.map((category) => {
                const counts = rollup.get(category.id);
                const deploymentSeverities = activeDeploymentId
                  ? activeSurface.deployment_category_severities?.[activeDeploymentId]
                  : undefined;
                const storedSeverity = activeDeploymentId
                  ? deploymentSeverities
                    ? deploymentSeverities[String(category.id)]
                    : activeSurface.category_severities?.[String(category.id)]
                  : activeSurface.category_severities?.[String(category.id)];
                const severity = storedSeverity ?? severityFromCounts(counts);
                const light = lightFromSeverity(severity);
                return (
                  <a
                    key={category.id}
                    href={`#surface-cat-${category.id}`}
                    class={cn(styles.categoryPill, styles[light])}
                    aria-label={`${category.name}: ${light}`}
                  >
                    <span>{category.short ?? category.id}</span>
                    <b>{counts?.total ?? 0}</b>
                  </a>
                );
              })}
            </div>
          </section>

          <section class={styles.section}>
            <div class={styles.sectionHead}>
              <span class={styles.num}>03</span>
              <h2>Categories and evidence</h2>
            </div>
            <div class={styles.factorGroups}>
              {categories.map((category) => {
                const rows = scoreRows.filter((row) => row.categoryId === category.id);
                if (rows.length === 0) return null;
                return (
                  <section
                    id={`surface-cat-${category.id}`}
                    class={styles.factorGroup}
                    key={category.id}
                  >
                    <header>
                      <h3>{category.name}</h3>
                      <span>{rows.length}</span>
                    </header>
                    <div class={styles.factorRows}>
                      {rows.map((row) => {
                        const href =
                          row.score !== 'green' && !reviewMode
                            ? `/protocols/${familySlug}/surfaces/${activeSurface.surface_slug}/factors/${row.factorId}/`
                            : undefined;
                        const content = (
                          <>
                            <span
                              class={cn(styles.scoreDot, styles[row.score])}
                              aria-hidden="true"
                            />
                            <span class={styles.factorMain}>
                              <b>
                                {row.factorId} / {row.factorName}
                              </b>
                              <small>
                                {row.evidence || row.gapReason || 'No evidence summary emitted.'}
                              </small>
                            </span>
                            <span class={styles.factorScore}>{row.score.replace(/_/g, ' ')}</span>
                          </>
                        );
                        return href ? (
                          <a class={styles.factorRow} href={href} key={row.factorId}>
                            {content}
                          </a>
                        ) : (
                          <div class={styles.factorRow} key={row.factorId}>
                            {content}
                          </div>
                        );
                      })}
                    </div>
                  </section>
                );
              })}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
