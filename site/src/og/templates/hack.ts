import { h, type SatoriNode } from '../render.ts';
import { COLORS, CARD, logoMark } from './_shared.ts';

export function hackCard(data: {
  id: string;
  protocolName: string;
  occurredAt?: string | null;
  lossUsd?: number | null;
  category?: string | null;
  chain?: string | null;
  factorIds?: string[];
  hasCritical?: boolean;
}): SatoriNode {
  function fmtLoss(v: number | null | undefined): string {
    if (v == null || v === 0) return 'N/A';
    if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
    if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
    if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
    return `$${v}`;
  }

  const topFactors = (data.factorIds ?? []).slice(0, 5);

  return h('div', {
    style: {
      ...CARD.outer,
      background: data.hasCritical ? COLORS.criticalBg : COLORS.bg,
      flexDirection: 'column',
      justifyContent: 'space-between',
    },
  } as never,
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
      logoMark(),
      data.hasCritical
        ? h('div', {
          style: {
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 16,
            color: COLORS.critical,
            fontWeight: 700,
          },
        }, '★ critical factor implicated')
        : null,
      h('div', {
        style: {
          fontSize: 52,
          fontWeight: 700,
          color: COLORS.ink,
          lineHeight: 1.1,
        },
      }, data.protocolName),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 24 } },
        data.occurredAt
          ? h('div', {
            style: { fontSize: 24, color: COLORS.muted, fontFamily: 'monospace' },
          }, data.occurredAt.slice(0, 10))
          : null,
        data.lossUsd
          ? h('div', {
            style: {
              fontSize: 28,
              fontWeight: 700,
              color: COLORS.gradeF,
            },
          }, fmtLoss(data.lossUsd))
          : null,
        data.category
          ? h('div', {
            style: {
              fontSize: 18,
              color: COLORS.muted,
              background: COLORS.white,
              padding: '4px 12px',
              borderRadius: 6,
              border: `1px solid ${COLORS.border}`,
            },
          }, data.category)
          : null,
        data.chain
          ? h('div', {
            style: { fontSize: 18, color: COLORS.muted },
          }, data.chain)
          : null,
      ),
      topFactors.length > 0
        ? h('div', { style: { display: 'flex', gap: 10, flexWrap: 'wrap' as never } },
          ...topFactors.map((fid) =>
            h('div', {
              style: {
                fontFamily: 'monospace',
                fontSize: 16,
                padding: '4px 12px',
                borderRadius: 6,
                background: COLORS.white,
                color: COLORS.muted,
                border: `1px solid ${COLORS.border}`,
              },
            }, fid),
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
      h('div', { style: { fontSize: 16, color: COLORS.muted } }, `defirisk.co`),
      h('div', { style: { flex: 1 } }),
      h('div', { style: { fontSize: 16, color: COLORS.muted } }, 'DeFi Risk · Incident reference'),
    ),
  );
}
