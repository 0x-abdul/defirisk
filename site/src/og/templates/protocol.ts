import { h, type SatoriNode } from '../render.ts';
import { COLORS, CARD, logoMark, gradePill, gradeColor } from './_shared.ts';

export function protocolCard(data: {
  name: string;
  slug: string;
  grade: string;
  chain?: string | null;
  tvl?: string | null;
  categoryLights?: Record<string, string>;
}): SatoriNode {
  const { text: gradeText } = gradeColor(data.grade);

  // Top 6 red/yellow categories for the mini grid
  const lights = data.categoryLights ?? {};
  const redCats = Object.entries(lights).filter(([, v]) => v === 'red').slice(0, 6);
  const yellowCats = Object.entries(lights).filter(([, v]) => v === 'yellow').slice(0, 6);

  return h('div', {
    style: {
      ...CARD.outer,
      background: COLORS.bg,
      flexDirection: 'column',
      justifyContent: 'space-between',
    },
  } as never,
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 20 } },
      logoMark(),
      h('div', { style: { display: 'flex', alignItems: 'flex-start', gap: 28 } },
        gradePill(data.grade, 96),
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
          h('div', {
            style: {
              fontSize: 42,
              fontWeight: 700,
              color: COLORS.ink,
              lineHeight: 1.1,
            },
          }, data.name),
          h('div', { style: { display: 'flex', gap: 12, alignItems: 'center' } },
            data.chain
              ? h('div', {
                style: { fontSize: 18, color: COLORS.muted },
              }, data.chain)
              : null,
            data.tvl
              ? h('div', {
                style: {
                  fontSize: 18,
                  color: COLORS.muted,
                  fontFamily: 'monospace',
                },
              }, `TVL: ${data.tvl}`)
              : null,
          ),
        ),
      ),
      redCats.length + yellowCats.length > 0
        ? h('div', { style: { display: 'flex', gap: 10, flexWrap: 'wrap' as never } },
          ...redCats.map(([cat]) =>
            h('div', {
              style: {
                padding: '4px 12px',
                borderRadius: 6,
                background: COLORS.gradeFbg,
                color: COLORS.gradeF,
                fontSize: 14,
                fontWeight: 600,
              },
            }, cat),
          ),
          ...yellowCats.map(([cat]) =>
            h('div', {
              style: {
                padding: '4px 12px',
                borderRadius: 6,
                background: COLORS.gradeCbg,
                color: COLORS.gradeC,
                fontSize: 14,
                fontWeight: 600,
              },
            }, cat),
          ),
        )
        : null,
    ),
    h('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        paddingTop: 20,
        borderTop: `2px solid ${COLORS.border}`,
      },
    },
      h('div', { style: { fontSize: 16, color: COLORS.muted } }, `defirisk.co/protocols/${data.slug}/`),
      h('div', { style: { flex: 1 } }),
      h('div', {
        style: { fontSize: 22, fontWeight: 700, color: gradeText },
      }, `Grade ${data.grade}`),
    ),
  );
}
