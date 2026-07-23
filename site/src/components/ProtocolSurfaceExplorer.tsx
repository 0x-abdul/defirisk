import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { findDeployment, readFamilyViewState, writeFamilyViewState } from '../lib/family-view-url';
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
interface FactorCounts {
  rubric_total?: number;
  assessed?: number;
  severity_rated?: number;
  pending?: number;
  not_applicable?: number;
  unscored?: number;
}
interface DeploymentEntry {
  id?: string;
  chain?: string;
  display_name?: string | null;
  tvs_usd?: number | string | null;
  deployment_key?: string | null;
  selector?: { deployment_key?: string | null; chain?: string | null };
  factor_counts?: FactorCounts;
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
  is_primary?: boolean;
  category_severities?: Record<string, number> | null;
  deployments?: DeploymentEntry[];
  factor_scores?: ScoreEntry[];
  deployment_factor_scores?: Record<string, ScoreEntry[]>;
  deployment_category_severities?: Record<string, Record<string, number>>;
  factor_counts?: FactorCounts;
  deployment_count?: number;
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
const cn = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(' ');
const n = (value: unknown) =>
  typeof value === 'number'
    ? value
    : typeof value === 'string' && Number.isFinite(Number(value))
      ? Number(value)
      : null;
const usd = (value: unknown) => {
  const valueAsNumber = n(value);
  if (!valueAsNumber || valueAsNumber < 0) return 'Unavailable';
  if (valueAsNumber >= 1e9) return `$${(valueAsNumber / 1e9).toFixed(1)}B`;
  if (valueAsNumber >= 1e6) return `$${(valueAsNumber / 1e6).toFixed(1)}M`;
  return `$${valueAsNumber.toFixed(0)}`;
};
const date = (value?: string | null) =>
  value
    ? new Date(value).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    : 'Unavailable';
const label = (value?: string) => (value ? value.replace(/_/g, ' ') : 'Active');
const severity = (counts?: { red: number; yellow: number; green: number }) => {
  const total = (counts?.red ?? 0) + (counts?.yellow ?? 0) + (counts?.green ?? 0);
  return total ? (((counts?.red ?? 0) * 3 + (counts?.yellow ?? 0)) / (total * 3)) * 100 : undefined;
};
const tone = (value?: number) =>
  value === undefined ? 'gray' : value >= 50 ? 'red' : value >= 20 ? 'yellow' : 'green';

export default function ProtocolSurfaceExplorer({
  familySlug,
  surfaces,
  categories,
  factors,
  reviewMode = false,
  legacyCaveat,
}: Props) {
  const primary = surfaces.find((surface) => surface.is_primary) ??
    surfaces[0] ?? { surface_slug: 'default' };
  const [surfaceSlug, setSurfaceSlug] = useState(
    surfaces.length > 1 ? '__overview' : (primary.surface_slug ?? 'default')
  );
  const [deploymentId, setDeploymentId] = useState('');
  const [sheetOpen, setSheetOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(
    () =>
      new Set(
        typeof window !== 'undefined' && window.innerWidth >= 1024
          ? categories.map(({ id }) => id)
          : []
      )
  );
  const trigger = useRef<HTMLButtonElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  const factorById = useMemo(
    () => new Map(factors.map((factor) => [factor.id, factor])),
    [factors]
  );
  const activeSurface = surfaces.find((surface) => surface.surface_slug === surfaceSlug) ?? primary;
  const deployments = activeSurface.deployments ?? [];
  const selectedDeployment =
    deployments.find((deployment) => deployment.id === deploymentId) ?? null;

  const applyLocation = (replace = true) => {
    const requested = readFamilyViewState(window.location.search);
    const selectedSurface =
      requested.surface && surfaces.some((surface) => surface.surface_slug === requested.surface)
        ? requested.surface
        : surfaces.length > 1
          ? '__overview'
          : (primary.surface_slug ?? 'default');
    const nextSurface =
      surfaces.find((surface) => surface.surface_slug === selectedSurface) ?? primary;
    const nextDeployment =
      selectedSurface === '__overview'
        ? null
        : findDeployment(nextSurface.deployments ?? [], requested);
    setSurfaceSlug(selectedSurface);
    setDeploymentId(nextDeployment?.id ?? '');
    const canonical = writeFamilyViewState(
      window.location.pathname,
      window.location.search,
      selectedSurface === '__overview' ? null : selectedSurface,
      nextDeployment
    );
    if (replace && canonical !== `${window.location.pathname}${window.location.search}`)
      window.history.replaceState({}, '', canonical);
  };

  useEffect(() => {
    applyLocation();
    const onPop = () => applyLocation(false);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [surfaces]);
  useEffect(() => {
    if (!sheetOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setSheetOpen(false);
        return;
      }
      if (event.key !== 'Tab' || !sheet.current) return;
      const focusable = [
        ...sheet.current.querySelectorAll<HTMLElement>(
          'button,[href],[tabindex]:not([tabindex="-1"])'
        ),
      ];
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    requestAnimationFrame(() =>
      sheet.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus()
    );
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
      trigger.current?.focus();
    };
  }, [sheetOpen]);
  useEffect(() => {
    const match = window.location.hash.match(/^#(?:surface-cat-)?(\d+)$/);
    if (match) setExpanded((current) => new Set([...current, Number(match[1])]));
  }, [surfaceSlug]);

  const navigate = (
    nextSurface: string,
    nextDeployment: DeploymentEntry | null,
    replace = false
  ) => {
    setSurfaceSlug(nextSurface);
    setDeploymentId(nextDeployment?.id ?? '');
    const href = writeFamilyViewState(
      window.location.pathname,
      window.location.search,
      nextSurface === '__overview' ? null : nextSurface,
      nextDeployment
    );
    if (replace) window.history.replaceState({}, '', href);
    else window.history.pushState({}, '', href);
  };
  const rows = useMemo(() => {
    const raw = deploymentId
      ? (activeSurface.deployment_factor_scores?.[deploymentId] ?? activeSurface.factor_scores)
      : activeSurface.factor_scores;
    return (raw ?? [])
      .flatMap((score) => {
        const factor = factorById.get(score.factor_id ?? '');
        return factor ? [{ ...score, factor, score: score.score ?? 'gray' }] : [];
      })
      .sort(
        (a, b) =>
          (SCORE_ORDER[a.score] ?? 4) - (SCORE_ORDER[b.score] ?? 4) ||
          (a.factor_id ?? '').localeCompare(b.factor_id ?? '')
      );
  }, [activeSurface, deploymentId, factorById]);
  const counts = useMemo(
    () => ({
      red: rows.filter((row) => row.score === 'red').length,
      yellow: rows.filter((row) => row.score === 'yellow').length,
      green: rows.filter((row) => row.score === 'green').length,
    }),
    [rows]
  );
  const toggle = (id: number) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const groupRows = (id: number) => rows.filter((row) => row.factor.category_id === id);
  const familyDeployments = surfaces.reduce(
    (total, surface) => total + (surface.deployment_count ?? surface.deployments?.length ?? 0),
    0
  );
  const deploymentValue = selectedDeployment?.tvs_usd ?? null;
  const activeCounts = selectedDeployment?.factor_counts ?? activeSurface.factor_counts;

  return (
    <div class={styles.shell}>
      <div class={styles.surfaceLabel}>SURFACES</div>
      <div class={styles.tabScroller}>
        <div class={styles.tabs} role="tablist" aria-label="Protocol surfaces">
          {surfaces.length > 1 && (
            <button
              type="button"
              class={cn(styles.tab, surfaceSlug === '__overview' && styles.active)}
              role="tab"
              aria-selected={surfaceSlug === '__overview'}
              onClick={() => navigate('__overview', null)}
            >
              Overview
            </button>
          )}
          {surfaces.map((surface) => (
            <button
              key={surface.surface_slug}
              type="button"
              class={cn(styles.tab, surfaceSlug === surface.surface_slug && styles.active)}
              role="tab"
              aria-selected={surfaceSlug === surface.surface_slug}
              aria-label={surface.display_name ?? surface.surface_slug}
              onClick={() => navigate(surface.surface_slug ?? 'default', null)}
            >
              {surface.display_name ?? surface.surface_slug}
            </button>
          ))}
        </div>
      </div>
      {surfaceSlug === '__overview' ? (
        <section class={styles.section}>
          <div class={styles.sectionHead}>
            <span class={styles.num}>01</span>
            <div>
              <h2>Family overview</h2>
              <p>Grades are assessed per surface — this family has no aggregate grade.</p>
            </div>
            <span>
              {surfaces.length} surfaces · {familyDeployments} deployments
            </span>
          </div>
          {legacyCaveat && <p class={styles.caveat}>{legacyCaveat}</p>}
          <table class={styles.compare}>
            <thead>
              <tr>
                <th>Surface</th>
                <th>Status</th>
                <th>TVS</th>
                <th>Grade</th>
                <th>Score</th>
                <th>Reviewed</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {surfaces.map((surface) => (
                <tr key={surface.surface_slug}>
                  <td data-label="Surface">
                    <b>{surface.display_name ?? surface.surface_slug}</b>
                    {surface.is_primary && <small class={styles.primary}>Primary</small>}
                  </td>
                  <td data-label="Lifecycle">
                    <span class={styles.status}>{label(surface.status)}</span>
                  </td>
                  <td data-label="TVS">{usd(surface.tvs_usd)}</td>
                  <td data-label="Grade">
                    <span class={styles.grade}>{surface.headline_grade ?? 'Pending'}</span>
                  </td>
                  <td data-label="Risk">
                    {n(surface.risk_score)?.toFixed(1) ?? 'Pending publication'}
                  </td>
                  <td data-label="Reviewed">{date(surface.graded_at)}</td>
                  <td>
                    <button
                      class={styles.linkButton}
                      type="button"
                      onClick={() => navigate(surface.surface_slug ?? 'default', null)}
                    >
                      View surface
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        <>
          <section class={styles.summary} aria-live="polite">
            <div>
              <span class={styles.owner}>
                Surface grade · {activeSurface.display_name ?? activeSurface.surface_slug}
                {selectedDeployment ? ' — applies to this deployment' : ''}
              </span>
              <h2>{activeSurface.display_name ?? activeSurface.surface_slug}</h2>
              <p>
                {label(activeSurface.status)}
                {selectedDeployment
                  ? ` · ${selectedDeployment.chain ?? selectedDeployment.display_name}`
                  : ' · All deployments'}
              </p>
            </div>
            <div class={styles.gradeBox}>
              <b>{activeSurface.headline_grade ?? 'Pending'}</b>
              <span>{n(activeSurface.risk_score)?.toFixed(1) ?? '—'} risk</span>
            </div>
          </section>
          {deployments.length > 0 && (
            <section class={styles.deploymentControl} aria-label="Deployment selection">
              <span>DEPLOYMENTS</span>
              <button
                ref={trigger}
                type="button"
                class={styles.deploymentTrigger}
                aria-haspopup="dialog"
                aria-expanded={sheetOpen}
                onClick={() => setSheetOpen(true)}
              >
                {selectedDeployment?.display_name ?? selectedDeployment?.chain ?? 'All deployments'}{' '}
                <b>⌄</b>
              </button>
              <p>
                {selectedDeployment
                  ? `${selectedDeployment.chain ?? 'Deployment'} · ${usd(deploymentValue)} TVS`
                  : `${deployments.length} selectable deployments`}{' '}
              </p>
            </section>
          )}
          <div class={styles.metrics}>
            <span>
              <b>{selectedDeployment ? usd(deploymentValue) : usd(activeSurface.tvs_usd)}</b> TVS{' '}
              {selectedDeployment && <em>deployment-scoped</em>}
            </span>
            <span>
              <b>{date(activeSurface.graded_at)}</b> Reviewed{' '}
              <em>{selectedDeployment ? 'Surface-wide' : ''}</em>
            </span>
            <span>
              <b>{activeCounts?.assessed ?? counts.red + counts.yellow + counts.green} assessed</b>{' '}
              <em>{selectedDeployment ? 'Effective deployment evidence' : ''}</em>
            </span>
            <span>
              <b>
                {counts.red} / {counts.yellow} / {counts.green}
              </b>{' '}
              R/Y/G <em>{selectedDeployment ? 'Effective deployment evidence' : ''}</em>
            </span>
          </div>
          <section class={styles.section}>
            <div class={styles.sectionHead}>
              <span class={styles.num}>02</span>
              <div>
                <h2>Risk profile</h2>
                <p>
                  {activeCounts?.rubric_total
                    ? `${activeCounts.rubric_total} rubric factors · ${activeCounts.pending ?? 0} pending`
                    : `${rows.length} factors assessed`}
                </p>
              </div>
            </div>
            <div class={styles.categoryGrid}>
              {categories.map((category) => {
                const local = groupRows(category.id);
                const breakdown = {
                  red: local.filter((row) => row.score === 'red').length,
                  yellow: local.filter((row) => row.score === 'yellow').length,
                  green: local.filter((row) => row.score === 'green').length,
                };
                const supplied = deploymentId
                  ? activeSurface.deployment_category_severities?.[deploymentId]?.[
                      String(category.id)
                    ]
                  : activeSurface.category_severities?.[String(category.id)];
                const color = tone(supplied ?? severity(breakdown));
                return (
                  <button
                    type="button"
                    key={category.id}
                    class={cn(styles.categoryPill, styles[color])}
                    onClick={() => {
                      setExpanded((current) => new Set([...current, category.id]));
                      document
                        .getElementById(`surface-cat-${category.id}`)
                        ?.scrollIntoView({ behavior: 'smooth' });
                    }}
                    aria-label={`${category.name}: ${color}, ${local.length} factors`}
                  >
                    <span>{category.short ?? category.name}</span>
                    <b>{local.length}</b>
                  </button>
                );
              })}
            </div>
          </section>
          <section class={styles.section}>
            <div class={styles.sectionHead}>
              <span class={styles.num}>03</span>
              <div>
                <h2>Categories and evidence</h2>
                <p>Evidence retains factor IDs, source detail, and individual factor routes.</p>
              </div>
              <div class={styles.evidenceActions}>
                <button
                  type="button"
                  onClick={() => setExpanded(new Set(categories.map(({ id }) => id)))}
                >
                  Expand all
                </button>
                <button type="button" onClick={() => setExpanded(new Set())}>
                  Collapse all
                </button>
              </div>
            </div>
            <div class={styles.factorGroups}>
              {categories.map((category) => {
                const categoryRows = groupRows(category.id);
                if (!categoryRows.length) return null;
                const open = expanded.has(category.id);
                return (
                  <section
                    id={`surface-cat-${category.id}`}
                    class={styles.factorGroup}
                    key={category.id}
                    tabIndex={-1}
                  >
                    <button
                      type="button"
                      class={styles.factorHeader}
                      aria-expanded={open}
                      onClick={() => toggle(category.id)}
                    >
                      <span>
                        <b>{category.name}</b>
                        <small>
                          {categoryRows.length} factors assessed · Top concerns:{' '}
                          {categoryRows
                            .filter((row) => row.score !== 'green')
                            .slice(0, 2)
                            .map((row) => row.factor_id)
                            .join(', ') || 'none'}
                        </small>
                      </span>
                      <span>{open ? '−' : '+'}</span>
                    </button>
                    {open && (
                      <div class={styles.factorRows}>
                        {categoryRows.map((row) => {
                          const href =
                            row.score !== 'green' && !reviewMode
                              ? `/protocols/${familySlug}/surfaces/${activeSurface.surface_slug}/factors/${row.factor_id}/`
                              : undefined;
                          const contents = (
                            <>
                              <span
                                class={cn(styles.scoreDot, styles[row.score])}
                                aria-hidden="true"
                              />
                              <span class={styles.factorMain}>
                                <b>
                                  {row.factor_id} / {row.factor.name}
                                </b>
                                <small>
                                  {row.evidence_summary ||
                                    row.gap_reason ||
                                    'No evidence summary emitted.'}
                                </small>
                              </span>
                              <span class={styles.factorScore}>{row.score.replace(/_/g, ' ')}</span>
                            </>
                          );
                          return href ? (
                            <a class={styles.factorRow} href={href} key={row.factor_id}>
                              {contents}
                            </a>
                          ) : (
                            <div class={styles.factorRow} key={row.factor_id}>
                              {contents}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
          </section>
        </>
      )}
      {sheetOpen && (
        <div
          class={styles.sheetBackdrop}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setSheetOpen(false);
          }}
        >
          <div
            class={styles.sheet}
            ref={sheet}
            role="dialog"
            aria-modal="true"
            aria-label="Select deployment"
          >
            <header>
              <b>Deployments</b>
              <button type="button" onClick={() => setSheetOpen(false)}>
                Close
              </button>
            </header>
            <div class={styles.sheetOptions}>
              <button
                type="button"
                aria-selected={!selectedDeployment}
                onClick={() => {
                  navigate(activeSurface.surface_slug ?? 'default', null);
                  setSheetOpen(false);
                }}
              >
                All deployments
              </button>
              {deployments.map((deployment) => (
                <button
                  key={deployment.id ?? deployment.deployment_key}
                  type="button"
                  aria-selected={deployment.id === deploymentId}
                  onClick={() => {
                    navigate(activeSurface.surface_slug ?? 'default', deployment);
                    setSheetOpen(false);
                  }}
                >
                  {deployment.display_name ??
                    deployment.chain ??
                    deployment.deployment_key ??
                    'Deployment'}
                  <small>
                    {deployment.chain ?? 'Unknown chain'} · {usd(deployment.tvs_usd)}
                  </small>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
