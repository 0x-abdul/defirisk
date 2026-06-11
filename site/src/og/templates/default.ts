import { h, type SatoriNode } from '../render.ts';
import { COLORS, CARD, logoMark } from './_shared.ts';

export function defaultCard(data: {
  title?: string;
  description?: string;
}): SatoriNode {
  const title = data.title ?? 'DeFi Risk';
  const description = data.description ?? 'A field guide for DeFi risk. Open-source rubric, neutral.';

  return h('div', {
    style: {
      ...CARD.outer,
      background: COLORS.bg,
      flexDirection: 'column',
      justifyContent: 'space-between',
    },
    children: [
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
        logoMark(),
        h('div', {
          style: {
            fontSize: 52,
            fontWeight: 700,
            color: COLORS.ink,
            lineHeight: 1.1,
            maxWidth: 900,
          },
        }, title),
        h('div', {
          style: { fontSize: 26, color: COLORS.muted, maxWidth: 820, lineHeight: 1.4 },
        }, description),
      ),
      h('div', {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          paddingTop: 24,
          borderTop: `2px solid ${COLORS.border}`,
        },
      },
        h('div', { style: { fontSize: 18, color: COLORS.muted } }, 'defirisk.co'),
        h('div', { style: { flex: 1 } }),
        h('div', {
          style: {
            fontSize: 16,
            color: COLORS.muted,
            fontFamily: 'monospace',
          },
        }, 'CC-BY 4.0 · MIT'),
      ),
    ],
  } as never);
}
