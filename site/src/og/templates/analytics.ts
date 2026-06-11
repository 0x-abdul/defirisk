import { h, type SatoriNode } from '../render.ts';
import { COLORS, CARD, logoMark } from './_shared.ts';

export function analyticsCard(data: {
  protocolCount?: number;
  factorCount?: number;
  hackCount?: number;
  tvsTotal?: string;
}): SatoriNode {
  const stats = [
    { label: 'Protocols graded', value: String(data.protocolCount ?? '57') },
    { label: 'Evidence factors', value: String(data.factorCount ?? '184') },
    { label: 'Hacks indexed', value: String(data.hackCount ?? '311') },
    { label: 'TVL covered', value: data.tvsTotal ?? '—' },
  ];

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
      h('div', {
        style: {
          fontSize: 52,
          fontWeight: 700,
          color: COLORS.ink,
          lineHeight: 1.1,
        },
      }, 'Grade distribution & trends'),
      h('div', {
        style: {
          fontSize: 24,
          color: COLORS.muted,
          lineHeight: 1.4,
        },
      }, 'How DeFi risk grades evolve across the protocol universe over time.'),
      h('div', { style: { display: 'flex', gap: 32, marginTop: 8 } },
        ...stats.map((s) =>
          h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
            h('div', { style: { fontSize: 32, fontWeight: 700, color: COLORS.ink } }, s.value),
            h('div', { style: { fontSize: 15, color: COLORS.muted } }, s.label),
          ),
        ),
      ),
    ),
    h('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        paddingTop: 20,
        borderTop: `2px solid ${COLORS.border}`,
      },
    },
      h('div', { style: { fontSize: 16, color: COLORS.muted } }, 'defirisk.co/analytics/'),
      h('div', { style: { flex: 1 } }),
      h('div', { style: { fontSize: 16, color: COLORS.muted } }, 'DeFi Risk'),
    ),
  );
}
