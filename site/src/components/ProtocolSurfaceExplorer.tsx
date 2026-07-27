import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'preact/hooks';
import FactorAssessment from './FactorAssessment';
import type { AssessmentFactorMeta, AssessmentScore } from './FactorAssessment.types';
import { buildFactorAssessmentModel, mergeAssessmentScores } from '../lib/factor-assessment-model';
import {
  buildAssessmentHeaderModel,
  finiteNumber,
  formatAssessmentDateUtc,
  GRADE_MEANING,
} from '../lib/assessment-header-model';
import {
  findDeployment,
  readFamilyViewState,
  selectDefaultSurface,
  writeFamilyViewState,
  type FamilyViewMode,
} from '../lib/family-view-url';
import styles from './ProtocolSurfaceExplorer.module.css';

interface CategoryMeta {
  id: number;
  name: string;
  short?: string;
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
  cap_applied?: 'none' | 'D' | 'F' | null;
  cap_reason?: string | null;
  scope_note?: string | null;
  is_primary?: boolean;
  category_lights?: Record<string, 'red' | 'yellow' | 'green' | 'gray'> | null;
  category_severities?: Record<string, number> | null;
  deployments?: DeploymentEntry[];
  factor_scores?: AssessmentScore[];
  deployment_overrides?: Record<string, AssessmentScore[]>;
  deployment_factor_scores?: Record<string, AssessmentScore[]>;
  deployment_category_severities?: Record<string, Record<string, number>>;
  factor_counts?: FactorCounts;
  deployment_count?: number;
}

interface Props {
  familySlug: string;
  surfaces: SurfaceEntry[];
  categories: CategoryMeta[];
  factors: AssessmentFactorMeta[];
  reviewMode?: boolean;
  legacyCaveat?: string | null;
}

const cn = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(' ');

const usd = (value: unknown) => {
  const valueAsNumber = finiteNumber(value);
  if (valueAsNumber === null || valueAsNumber < 0) return 'Unavailable';
  if (valueAsNumber >= 1e9) return `$${(valueAsNumber / 1e9).toFixed(1)}B`;
  if (valueAsNumber >= 1e6) return `$${(valueAsNumber / 1e6).toFixed(1)}M`;
  return `$${valueAsNumber.toFixed(0)}`;
};

const lifecycleLabel = (value?: string) => (value ? value.replace(/_/g, ' ') : 'Active');

function setText(selector: string, value: string) {
  document.querySelectorAll<HTMLElement>(selector).forEach((element) => {
    element.textContent = value;
  });
}

function setHidden(selector: string, hidden: boolean) {
  document.querySelectorAll<HTMLElement>(selector).forEach((element) => {
    element.hidden = hidden;
  });
}

export default function ProtocolSurfaceExplorer({
  familySlug,
  surfaces,
  categories,
  factors,
  reviewMode = false,
  legacyCaveat,
}: Props) {
  const defaultSurface = selectDefaultSurface(surfaces) ??
    surfaces[0] ?? { surface_slug: 'default' };
  const defaultSlug = defaultSurface.surface_slug ?? 'default';
  const [mode, setMode] = useState<FamilyViewMode>('default');
  const [surfaceSlug, setSurfaceSlug] = useState(defaultSlug);
  const [deploymentId, setDeploymentId] = useState('');
  const [sheetOpen, setSheetOpen] = useState(false);
  const [locationParts, setLocationParts] = useState({
    pathname: '',
    search: '',
    hash: '',
  });
  const trigger = useRef<HTMLButtonElement>(null);
  const sheet = useRef<HTMLDivElement>(null);

  const activeSurface =
    surfaces.find((surface) => surface.surface_slug === surfaceSlug) ?? defaultSurface;
  const deployments = activeSurface.deployments ?? [];
  const selectedDeployment =
    deployments.find((deployment) => deployment.id === deploymentId) ?? null;
  const deploymentScores = deploymentId
    ? activeSurface.deployment_factor_scores?.[deploymentId]
    : undefined;
  const deploymentOverrides = deploymentId
    ? activeSurface.deployment_overrides?.[deploymentId]
    : undefined;
  const effectiveScores = useMemo(
    () => mergeAssessmentScores(activeSurface.factor_scores, deploymentScores),
    [activeSurface, deploymentScores]
  );
  const evidenceScopeLabel = useMemo(() => {
    if (!selectedDeployment) return '';
    const overrideIds = new Set(
      (deploymentOverrides ?? []).map((score) => score.factor_id).filter(Boolean)
    );
    if (!overrideIds.size) return 'Surface evidence fallback';
    const usesSurfaceFallback = (activeSurface.factor_scores ?? []).some(
      (score) => score.factor_id && !overrideIds.has(score.factor_id)
    );
    return usesSurfaceFallback ? 'Deployment overrides + surface fallback' : 'Deployment evidence';
  }, [activeSurface.factor_scores, deploymentOverrides, selectedDeployment]);
  const effectiveSeverities = useMemo(() => {
    if (!deploymentId) return activeSurface.category_severities ?? {};
    const deploymentSeverities = activeSurface.deployment_category_severities?.[deploymentId];
    // Exported deployment severities describe the full effective deployment
    // assessment. A missing category means its effective denominator is zero,
    // so retaining the surface severity would contradict the selected rows.
    return deploymentSeverities ?? activeSurface.category_severities ?? {};
  }, [activeSurface, deploymentId]);
  const assessment = useMemo(
    () =>
      buildFactorAssessmentModel({
        context: {
          protocolSlug: familySlug,
          surfaceSlug: activeSurface.surface_slug ?? null,
          deploymentId: selectedDeployment?.id ?? null,
        },
        categories,
        factors,
        scores: effectiveScores,
        categoryLights: selectedDeployment ? null : activeSurface.category_lights,
        categorySeverities: effectiveSeverities,
        reviewMode,
        factorHref: (factorId, light) =>
          light !== 'green' && !reviewMode
            ? `/protocols/${familySlug}/surfaces/${activeSurface.surface_slug}/factors/${factorId}/`
            : undefined,
      }),
    [
      activeSurface,
      categories,
      effectiveScores,
      effectiveSeverities,
      factors,
      familySlug,
      reviewMode,
      selectedDeployment?.id,
    ]
  );
  const header = useMemo(
    () =>
      buildAssessmentHeaderModel({
        mode,
        headlineGrade: activeSurface.headline_grade,
        riskScore: activeSurface.risk_score,
        gradedAt: activeSurface.graded_at,
        status: activeSurface.status,
        scopeNote: activeSurface.scope_note,
        capApplied: activeSurface.cap_applied,
        capReason: activeSurface.cap_reason,
        factorAssessment: assessment,
      }),
    [activeSurface, assessment, mode]
  );

  const hrefFor = (
    nextMode: FamilyViewMode,
    nextSurface: SurfaceEntry | null,
    nextDeployment: DeploymentEntry | null
  ) =>
    writeFamilyViewState(
      locationParts.pathname,
      locationParts.search,
      nextSurface?.surface_slug ?? null,
      nextDeployment,
      nextMode,
      locationParts.hash
    ) || '?';

  const applyLocation = () => {
    const currentHash = window.location.hash;
    const requested = readFamilyViewState(window.location.search);
    if (requested.mode === 'overview') {
      setMode('overview');
      setSurfaceSlug(defaultSlug);
      setDeploymentId('');
      const canonical = writeFamilyViewState(
        window.location.pathname,
        window.location.search,
        null,
        null,
        'overview',
        currentHash
      );
      if (canonical !== `${window.location.pathname}${window.location.search}${currentHash}`)
        window.history.replaceState({}, '', canonical);
      setLocationParts({
        pathname: window.location.pathname,
        search: window.location.search,
        hash: window.location.hash,
      });
      return;
    }

    const explicitSurface =
      requested.mode === 'surface'
        ? surfaces.find((surface) => surface.surface_slug === requested.surface)
        : null;
    const nextSurface = explicitSurface ?? defaultSurface;
    const nextMode: FamilyViewMode = explicitSurface ? 'surface' : 'default';
    const nextDeployment =
      requested.mode === 'surface' && !explicitSurface
        ? null
        : findDeployment(nextSurface.deployments ?? [], requested);
    setMode(nextMode);
    setSurfaceSlug(nextSurface.surface_slug ?? defaultSlug);
    setDeploymentId(nextDeployment?.id ?? '');
    const canonical = writeFamilyViewState(
      window.location.pathname,
      window.location.search,
      nextSurface.surface_slug ?? null,
      nextDeployment,
      nextMode,
      currentHash
    );
    if (canonical !== `${window.location.pathname}${window.location.search}${currentHash}`)
      window.history.replaceState({}, '', canonical);
    setLocationParts({
      pathname: window.location.pathname,
      search: window.location.search,
      hash: window.location.hash,
    });
  };

  useEffect(() => {
    applyLocation();
    const onPop = () => applyLocation();
    const onHashChange = () =>
      setLocationParts({
        pathname: window.location.pathname,
        search: window.location.search,
        hash: window.location.hash,
      });
    window.addEventListener('popstate', onPop);
    window.addEventListener('hashchange', onHashChange);
    return () => {
      window.removeEventListener('popstate', onPop);
      window.removeEventListener('hashchange', onHashChange);
    };
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
      sheet.current?.querySelector<HTMLElement>('[aria-pressed="true"]')?.focus()
    );
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
      trigger.current?.focus();
    };
  }, [sheetOpen]);

  useEffect(() => {
    const match = window.location.hash.match(/^#cat-(\d+)$/);
    if (!match) return;
    const details = document.getElementById(`cat-${match[1]}`) as HTMLDetailsElement | null;
    if (details) details.open = true;
  }, [mode, surfaceSlug, deploymentId, locationParts.hash]);

  useLayoutEffect(() => {
    const { overview, grade: letter, riskScore } = header;
    const scored = Boolean(letter);

    setHidden('[data-family-grade-scored]', !scored);
    setHidden('[data-family-grade-empty]', scored);
    setHidden('[data-family-verdict]', !scored);
    setHidden('[data-family-field="risk-row"]', overview || riskScore === null);
    setHidden('[data-family-field="body-risk-row"]', overview || riskScore === null);

    const empty = document.querySelector<HTMLElement>('[data-family-grade-empty]');
    if (empty) {
      empty.setAttribute('aria-label', overview ? 'No aggregate grade' : 'Not yet scored');
      const label = empty.querySelector<HTMLElement>('.m');
      if (label) label.textContent = overview ? 'No aggregate grade' : 'Pending';
    }

    if (letter && !overview) {
      const grade = document.querySelector<HTMLElement>('[data-family-grade-scored] .gradebig');
      if (grade) {
        ['A', 'B', 'C', 'D', 'F'].forEach((candidate) => grade.classList.remove(candidate));
        grade.classList.add(letter);
        grade.setAttribute(
          'aria-label',
          `Grade ${letter}, ${GRADE_MEANING[letter]}${riskScore === null ? '' : `, risk score ${riskScore.toFixed(1)}`}`
        );
        const gradeLetter = grade.querySelector<HTMLElement>('.l');
        const meaning = grade.querySelector<HTMLElement>('.m');
        const score = grade.querySelector<HTMLElement>('.n');
        if (gradeLetter) gradeLetter.textContent = letter;
        if (meaning) meaning.textContent = GRADE_MEANING[letter];
        if (score) {
          score.textContent = riskScore === null ? '' : riskScore.toFixed(1);
          score.hidden = riskScore === null;
        }
      }
      const verdict = document.querySelector<HTMLElement>('[data-family-verdict] .verdict');
      const verdictMeaning = verdict?.querySelector<HTMLElement>('b');
      if (verdictMeaning) verdictMeaning.textContent = `${header.meaning}.`;
      if (verdictMeaning?.nextSibling)
        verdictMeaning.nextSibling.textContent = ` ${header.verdict}`;
    }

    setText('[data-family-field="reviewed"]', header.reviewed);
    setText('[data-family-field="body-reviewed"]', header.reviewed);
    setText('[data-family-field="critical"]', header.criticalText);
    document.querySelectorAll<HTMLElement>('[data-family-field="critical"]').forEach((element) => {
      element.style.color = !overview && assessment.criticalRed > 0 ? 'var(--gF)' : '';
    });
    setText('[data-family-field="severity"]', header.severityText);
    if (riskScore !== null && !overview) {
      setText('[data-family-field="risk"]', riskScore.toFixed(1));
      setText('[data-family-field="body-risk"]', riskScore.toFixed(1));
    }
    setText(
      '[data-family-field="provenance-date"]',
      overview ? 'N/A' : (activeSurface.graded_at?.slice(0, 19).replace('T', ' ') ?? 'N/A')
    );

    const cap = document.querySelector<HTMLElement>('[data-family-cap]');
    if (cap) {
      const visible = !overview && header.capApplied !== 'none' && Boolean(header.capReason);
      cap.hidden = !visible;
      cap.classList.toggle('cap-f', visible && header.capApplied === 'F');
      cap.classList.toggle('cap-d', visible && header.capApplied === 'D');
      const title = cap.querySelector<HTMLElement>('[data-family-cap-title]');
      const reason = cap.querySelector<HTMLElement>('[data-family-cap-reason]');
      const icon = cap.querySelector<HTMLElement>('.cap-icon');
      if (title) title.textContent = `Grade capped to ${header.capApplied}`;
      if (reason) reason.textContent = header.capReason ? ` ${header.capReason}` : '';
      if (icon) icon.textContent = header.capApplied === 'F' ? '⚠' : '▲';
    }
  }, [activeSurface.graded_at, assessment.criticalRed, header]);

  const navigate = (
    nextMode: FamilyViewMode,
    nextSurface: SurfaceEntry | null,
    nextDeployment: DeploymentEntry | null
  ) => {
    const resolvedSurface = nextSurface ?? defaultSurface;
    setMode(nextMode);
    setSurfaceSlug(resolvedSurface.surface_slug ?? defaultSlug);
    setDeploymentId(nextDeployment?.id ?? '');
    const href = writeFamilyViewState(
      window.location.pathname,
      window.location.search,
      resolvedSurface.surface_slug ?? null,
      nextDeployment,
      nextMode,
      window.location.hash
    );
    if (new URL(href, window.location.href).href !== window.location.href) {
      window.history.pushState({}, '', href);
    }
    setLocationParts({
      pathname: window.location.pathname,
      search: window.location.search,
      hash: window.location.hash,
    });
  };

  const activateAnchor = (
    event: MouseEvent,
    nextMode: FamilyViewMode,
    nextSurface: SurfaceEntry | null
  ) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    navigate(nextMode, nextSurface, null);
  };

  const onTabKeyDown = (event: KeyboardEvent) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tablist = event.currentTarget as HTMLElement | null;
    if (!tablist) return;
    const tabs = [...tablist.querySelectorAll<HTMLAnchorElement>('[role="tab"]')];
    const current = tabs.indexOf(document.activeElement as HTMLAnchorElement);
    if (current < 0) return;
    event.preventDefault();
    const nextIndex =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? tabs.length - 1
          : event.key === 'ArrowRight'
            ? (current + 1) % tabs.length
            : (current - 1 + tabs.length) % tabs.length;
    tabs[nextIndex]?.focus();
    tabs[nextIndex]?.click();
    tabs[nextIndex]?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  };

  const familyDeployments = surfaces.reduce(
    (total, surface) => total + (surface.deployment_count ?? surface.deployments?.length ?? 0),
    0
  );
  const deploymentValue = selectedDeployment?.tvs_usd ?? null;
  const assessed = assessment.assessedTotal;
  const activeTabId =
    mode === 'overview' ? 'family-tab-overview' : `family-tab-${activeSurface.surface_slug}`;

  return (
    <div class={styles.shell}>
      <div class={styles.visuallyHidden} aria-live="polite" aria-atomic="true">
        {mode === 'overview'
          ? 'Family overview selected'
          : `${activeSurface.display_name ?? activeSurface.surface_slug} assessment selected`}
      </div>
      <div class={styles.surfaceLabel}>SURFACES</div>
      <div class={styles.tabScroller}>
        <div
          class={styles.tabs}
          role="tablist"
          aria-label="Protocol surfaces"
          onKeyDown={onTabKeyDown}
        >
          {surfaces.length > 1 && (
            <a
              id="family-tab-overview"
              href={hrefFor('overview', null, null)}
              class={cn(styles.tab, mode === 'overview' && styles.active)}
              role="tab"
              aria-selected={mode === 'overview'}
              aria-controls="family-surface-panel"
              tabIndex={mode === 'overview' ? 0 : -1}
              onClick={(event) => activateAnchor(event, 'overview', null)}
            >
              Overview
            </a>
          )}
          {surfaces.map((surface) => {
            const selected =
              mode !== 'overview' && surface.surface_slug === activeSurface.surface_slug;
            return (
              <a
                id={`family-tab-${surface.surface_slug}`}
                key={surface.surface_slug}
                href={hrefFor('surface', surface, null)}
                class={cn(styles.tab, selected && styles.active)}
                role="tab"
                aria-selected={selected}
                aria-controls="family-surface-panel"
                tabIndex={selected ? 0 : -1}
                aria-label={surface.display_name ?? surface.surface_slug}
                onClick={(event) => activateAnchor(event, 'surface', surface)}
              >
                {surface.display_name ?? surface.surface_slug}
              </a>
            );
          })}
        </div>
      </div>

      <div id="family-surface-panel" role="tabpanel" aria-labelledby={activeTabId} tabIndex={0}>
        {mode === 'overview' ? (
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
                      <span class={styles.status}>{lifecycleLabel(surface.status)}</span>
                    </td>
                    <td data-label="TVS">{usd(surface.tvs_usd)}</td>
                    <td data-label="Grade">
                      <span class={styles.grade}>{surface.headline_grade ?? 'Pending'}</span>
                    </td>
                    <td data-label="Risk">
                      {finiteNumber(surface.risk_score)?.toFixed(1) ?? 'Pending publication'}
                    </td>
                    <td data-label="Reviewed">{formatAssessmentDateUtc(surface.graded_at)}</td>
                    <td>
                      <a
                        class={styles.linkButton}
                        href={hrefFor('surface', surface, null)}
                        onClick={(event) => activateAnchor(event, 'surface', surface)}
                      >
                        View surface
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : (
          <>
            <section class={styles.summary}>
              <div>
                <span class={styles.owner}>
                  Surface grade · {activeSurface.display_name ?? activeSurface.surface_slug}
                  {selectedDeployment ? ' — applies across deployments' : ''}
                </span>
                <h2>{activeSurface.display_name ?? activeSurface.surface_slug}</h2>
                <p>
                  {lifecycleLabel(activeSurface.status)}
                  {selectedDeployment
                    ? ` · ${selectedDeployment.chain ?? selectedDeployment.display_name}`
                    : ' · All deployments'}
                </p>
                {activeSurface.scope_note && <p>{activeSurface.scope_note}</p>}
              </div>
              <div class={styles.gradeBox}>
                <b>{activeSurface.headline_grade ?? 'Pending'}</b>
                <span>{header.riskScore?.toFixed(1) ?? '—'} risk</span>
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
                  {selectedDeployment?.display_name ??
                    selectedDeployment?.chain ??
                    'All deployments'}{' '}
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
                <b>{header.reviewed}</b> Reviewed{' '}
                <em>{selectedDeployment ? 'Surface-wide' : ''}</em>
              </span>
              <span>
                <b>{assessed} assessed</b> <em>{evidenceScopeLabel}</em>
              </span>
              <span>
                <b>
                  {assessment.totals.red} / {assessment.totals.yellow} / {assessment.totals.green}
                </b>{' '}
                R/Y/G <em>{evidenceScopeLabel}</em>
              </span>
            </div>

            <FactorAssessment model={assessment} />
          </>
        )}
      </div>

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
                aria-pressed={!selectedDeployment}
                onClick={() => {
                  navigate('surface', activeSurface, null);
                  setSheetOpen(false);
                }}
              >
                All deployments
              </button>
              {deployments.map((deployment) => (
                <button
                  key={deployment.id ?? deployment.deployment_key}
                  type="button"
                  aria-pressed={deployment.id === deploymentId}
                  onClick={() => {
                    navigate('surface', activeSurface, deployment);
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
