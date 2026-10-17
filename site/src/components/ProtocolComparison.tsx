import { useEffect, useState } from 'preact/hooks';
import type { AssessmentCategoryMeta, AssessmentFactorMeta } from './FactorAssessment.types';
import {
  buildComparisonColumn,
  comparisonDate,
  comparisonHref,
  readComparisonSearch,
  resolveComparisonSelections,
  type ComparisonProtocol,
  type ComparisonSelection,
} from '../lib/protocol-comparison';
import styles from './PublicTools.module.css';

interface Props {
  protocols: ComparisonProtocol[];
  categories: AssessmentCategoryMeta[];
  factors: AssessmentFactorMeta[];
}
export default function ProtocolComparison({ protocols, categories, factors }: Props) {
  const [selected, setSelected] = useState<ComparisonSelection[]>([]);
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const load = () => {
      const next = readComparisonSearch(window.location.search, protocols);
      setSelected(next);
      setReady(true);
      const requested = new URLSearchParams(window.location.search).getAll('protocol');
      setNotice(
        requested.length > next.length
          ? 'Unavailable or duplicate selections were removed. Compare up to four distinct published protocols.'
          : ''
      );
    };
    load();
    window.addEventListener('popstate', load);
    return () => window.removeEventListener('popstate', load);
  }, [protocols]);
  const update = (next: ComparisonSelection[]) => {
    const resolved = resolveComparisonSelections(next, protocols);
    setSelected(resolved);
    setNotice('');
    window.history.pushState({}, '', comparisonHref(resolved));
  };
  const columns = selected.flatMap((selection) => {
    const protocol = protocols.find((p) => p.slug === selection.protocol);
    const surface = protocol?.surfaces.find((s) => s.slug === selection.surface);
    return protocol && surface
      ? [buildComparisonColumn(protocol, surface, categories, factors)]
      : [];
  });
  if (protocols.length === 0)
    return (
      <p class={styles.notice}>
        No reviewed protocol assessments are published in this snapshot. Comparison will become
        available when public assessments are published.
      </p>
    );
  return (
    <div class={styles.tools}>
      <p>
        Choose two to four distinct protocols. Each column uses one published surface across its
        deployments. Different scopes, rubric versions and evidence dates can limit comparability.
        No combined score or grade is calculated.
      </p>
      <div class={styles.controls}>
        <label for="comparison-add">Add a protocol</label>
        <select
          id="comparison-add"
          disabled={!ready || selected.length >= 4}
          value=""
          onChange={(event) => {
            const slug = event.currentTarget.value;
            if (slug) update([...selected, { protocol: slug, surface: '' }]);
          }}
        >
          <option value="">Select a published protocol</option>
          {protocols
            .filter((p) => !selected.some((s) => s.protocol === p.slug))
            .map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
        </select>
      </div>
      {selected.length === 4 && <p>Four protocols selected. Remove one to add another.</p>}
      <p role="status">
        {notice ||
          (selected.length < 2
            ? 'Select at least two protocols to view the comparison.'
            : `${selected.length} protocols selected. This URL preserves the comparison.`)}
      </p>
      <div class={styles.cards}>
        {columns.map(({ protocol, surface }) => (
          <div key={protocol.slug} class={styles.card}>
            <a href={`/protocols/${protocol.slug}/?surface=${encodeURIComponent(surface.slug)}`}>
              {protocol.name}
            </a>
            <label for={`surface-${protocol.slug}`}>Surface for {protocol.name}</label>
            <select
              id={`surface-${protocol.slug}`}
              value={surface.slug}
              onChange={(event) =>
                update(
                  selected.map((s) =>
                    s.protocol === protocol.slug ? { ...s, surface: event.currentTarget.value } : s
                  )
                )
              }
            >
              {protocol.surfaces.map((s) => (
                <option key={s.slug} value={s.slug}>
                  {s.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => update(selected.filter((s) => s.protocol !== protocol.slug))}
            >
              Remove {protocol.name}
            </button>
          </div>
        ))}
      </div>
      {columns.length >= 2 && (
        <>
          <div
            class={styles.viewport}
            role="region"
            aria-label="Protocol comparison table"
            tabIndex={0}
          >
            <table class={styles.table}>
              <caption>Published assessments by selected surface</caption>
              <thead>
                <tr>
                  <th scope="col">Dimension</th>
                  {columns.map(({ protocol }) => (
                    <th key={protocol.slug} scope="col">
                      {protocol.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  {
                    label: 'Surface / scope',
                    values: columns.map(
                      ({ surface }) =>
                        `${surface.name}${surface.scope ? ` — ${surface.scope}` : ''}`
                    ),
                  },
                  {
                    label: 'Lifecycle',
                    values: columns.map(({ surface }) => surface.status.replaceAll('_', ' ')),
                  },
                  {
                    label: 'Published surfaces',
                    values: columns.map(({ protocol }) =>
                      protocol.surfaces.map((s) => s.name).join(', ')
                    ),
                  },
                  {
                    label: 'Deployments in selected surface',
                    values: columns.map(
                      ({ surface }) => surface.deployments.join(', ') || 'Unavailable'
                    ),
                  },
                  {
                    label: 'Rubric',
                    values: columns.map(({ protocol }) => protocol.rubricVersion),
                  },
                  {
                    label: 'Surface reviewed (UTC)',
                    values: columns.map(({ surface }) => comparisonDate(surface.reviewedAt)),
                  },
                  {
                    label: 'Severity-rated coverage',
                    values: columns.map(
                      ({ assessment }) =>
                        `${assessment.assessedTotal} / ${assessment.factorTotal} rubric factors`
                    ),
                  },
                  {
                    label: 'Not applicable',
                    values: columns.map(({ assessment }) =>
                      String(assessment.statusTotals.not_applicable)
                    ),
                  },
                  {
                    label: 'Pending / unknown / missing',
                    values: columns.map(
                      ({ assessment, missing }) =>
                        `${assessment.statusTotals.not_assessed} / ${assessment.statusTotals.gray} / ${missing}`
                    ),
                  },
                ].map((row) => (
                  <tr key={row.label}>
                    <th scope="row">{row.label}</th>
                    {row.values.map((value, i) => (
                      <td key={columns[i]?.protocol.slug}>{value}</td>
                    ))}
                  </tr>
                ))}
                {categories.map((category, index) => (
                  <tr key={category.id}>
                    <th scope="row">{category.name}</th>
                    {columns.map(({ protocol, assessment }) => {
                      const result = assessment.categories[index]!;
                      return (
                        <td key={protocol.slug}>
                          {result.light === 'gray' ? 'Unavailable' : result.light} ·{' '}
                          {result.assessedTotal}/{result.taxonomyTotal} severity rated
                          <br />
                          Severity:{' '}
                          {result.severity === undefined
                            ? 'Unavailable'
                            : `${result.severity.toFixed(1)}%`}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h2>Factor evidence</h2>
          <p>
            Missing, unknown, pending and not applicable factors are shown separately from
            severity-rated factors. Evidence dates are per factor; a review date is not a substitute
            for an evidence date.
          </p>
          {categories.map((category) => (
            <details key={category.id} class={styles.factorGroup}>
              <summary>{category.name} — factor details</summary>
              <div
                class={styles.viewport}
                role="region"
                aria-label={`${category.name} factor comparison`}
                tabIndex={0}
              >
                <table class={styles.table}>
                  <thead>
                    <tr>
                      <th scope="col">Factor</th>
                      {columns.map(({ protocol }) => (
                        <th key={protocol.slug} scope="col">
                          {protocol.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {factors
                      .filter((f) => f.category_id === category.id)
                      .map((factor) => (
                        <tr key={factor.id}>
                          <th scope="row">
                            <a href={`/factors/${factor.id}/`}>{factor.id}</a>
                            <br />
                            {factor.name}
                            {factor.is_critical && ' · Critical'}
                          </th>
                          {columns.map(({ protocol, surface }) => {
                            const score = surface.scores.find((s) => s.factor_id === factor.id);
                            return (
                              <td key={protocol.slug}>
                                <strong>
                                  {score
                                    ? String(score.score ?? 'gray').replaceAll('_', ' ')
                                    : 'Missing from public assessment'}
                                </strong>
                                <p>{score?.evidence_summary || 'Evidence summary unavailable.'}</p>
                                {score?.gap_reason && (
                                  <p>Gap: {score.gap_reason.replaceAll('_', ' ')}</p>
                                )}
                                <small>
                                  Evidence as of (UTC): {comparisonDate(score?.data_as_of)}
                                  <br />
                                  Collected (UTC): {comparisonDate(score?.collected_at)}
                                </small>
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </details>
          ))}
        </>
      )}
    </div>
  );
}
