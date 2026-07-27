import type { FactorLight, GapReason } from './FactorTable.types';
import type {
  CategoryLight,
  FactorAssessmentCategory,
  FactorAssessmentModel,
} from './FactorAssessment.types';
import styles from './FactorAssessment.module.css';

export interface FactorAssessmentProps {
  model: FactorAssessmentModel;
}

const LIGHT_LABELS: Record<CategoryLight, string> = {
  red: 'Red',
  yellow: 'Yellow',
  green: 'Green',
  gray: 'Gray',
};

function barHeight(index: number): number {
  return 6 + (index % 5) * 2.2;
}

function pipText(light: FactorLight): string {
  switch (light) {
    case 'red':
    case 'yellow':
    case 'green':
      return light;
    case 'not_assessed':
    case 'not_applicable':
      return 'n/a';
    case 'gray':
    default:
      return 'gray';
  }
}

function pipKind(light: FactorLight): 'red' | 'yellow' | 'green' | 'gray' {
  return light === 'red' || light === 'yellow' || light === 'green' ? light : 'gray';
}

function pipTooltip(light: FactorLight, gapReason?: GapReason | null): string | undefined {
  if (light === 'green' || light === 'yellow' || light === 'red') return undefined;
  if (light === 'not_applicable') return 'Not applicable to this protocol';

  switch (gapReason) {
    case 'protocol_opacity':
      return 'GRAY: protocol opaque (closed source / undocumented)';
    case 'pipeline_unimplemented':
      return 'GRAY: measurement pending (our pipeline gap, not a protocol issue)';
    case 'external_api_blocked':
      return 'GRAY: measurement pending (external API blocked)';
    case 'requires_curator_input':
      return 'GRAY: measurement pending (curator review needed)';
    case 'not_applicable':
      return 'GRAY: not applicable';
    default:
      return light === 'not_assessed' ? 'Not assessed' : 'GRAY: no measurement available';
  }
}

function FactorTable({ category }: { category: FactorAssessmentCategory }) {
  return (
    <div class={styles.ftable} role="list">
      {category.rows.map((factor) => {
        const content = (
          <>
            <span class={styles.fid}>{factor.factor_id}</span>
            <span>
              <span
                class={`${styles.pip} ${styles[pipKind(factor.light)]}`}
                title={pipTooltip(factor.light, factor.gap_reason)}
              >
                {pipText(factor.light)}
              </span>
            </span>
            <span class={styles.body}>
              <span class={styles.factorHead}>{factor.headline}</span>
              {factor.evidence && <span class={styles.ev}>{factor.evidence}</span>}
            </span>
          </>
        );

        return factor.href ? (
          <a
            key={factor.factor_id}
            role="listitem"
            class={`${styles.frow} ${styles.factorLink}`}
            href={factor.href}
          >
            {content}
          </a>
        ) : (
          <div key={factor.factor_id} role="listitem" class={styles.frow}>
            {content}
          </div>
        );
      })}
      {category.rows.length === 0 && (
        <div class={styles.empty}>No factor evidence yet for this category.</div>
      )}
    </div>
  );
}

function CategoryCard({ category }: { category: FactorAssessmentCategory }) {
  return (
    <details class={styles.catcard} id={`cat-${category.id}`} open>
      <summary class={styles.categoryHead}>
        <span class={styles.arrow} aria-hidden="true">
          ▾
        </span>
        <span class={styles.name}>{category.name}</span>
        <span class={styles.severity} aria-hidden="true">
          {category.bars.slice(0, 18).map((bar, index) => (
            <i
              key={`${bar}-${index}`}
              class={styles[bar]}
              style={{ height: `${barHeight(index)}px` }}
            />
          ))}
        </span>
        <span class={`${styles.light} ${styles[category.light]}`}>
          {LIGHT_LABELS[category.light]}
        </span>
        {typeof category.severity === 'number' && (
          <span class={`${styles.severityNumber} ${styles[category.light]}`}>
            {category.severity.toFixed(0)}
          </span>
        )}
        {category.count && <span class={styles.count}>{category.count}</span>}
      </summary>
      <FactorTable category={category} />
    </details>
  );
}

export default function FactorAssessment({ model }: FactorAssessmentProps) {
  return (
    <>
      <section class={styles.section}>
        <div class={styles.sectionHead}>
          <span class={styles.number}>01</span>
          <h2>Risk profile at a glance</h2>
          <span class={styles.right}>
            {model.categoryTotals.red} red · {model.categoryTotals.yellow} yellow ·{' '}
            {model.categoryTotals.green} green
          </span>
        </div>
        <div class={styles.categoryStrip}>
          {model.categories.map((category) => (
            <a
              key={category.id}
              href={`#cat-${category.id}`}
              class={`${styles.categoryKey} ${styles[category.light]}`}
              title={`${category.name} · ${category.light}`}
              aria-label={`${category.name} category: ${category.light}, ${category.taxonomyTotal} factors`}
            >
              {category.taxonomyTotal}
            </a>
          ))}
        </div>
      </section>

      <section class={styles.section}>
        <div class={styles.sectionHead}>
          <span class={styles.number}>02</span>
          <h2>Categories &amp; evidence</h2>
          <span class={styles.right}>
            {model.factorTotal} factors · {model.categories.length} categories
          </span>
        </div>

        {model.categories.map((category) => (
          <CategoryCard key={category.id} category={category} />
        ))}
      </section>
    </>
  );
}
