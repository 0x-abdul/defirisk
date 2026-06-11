import { h, type SatoriNode } from '../render.ts';
import { COLORS, CARD, logoMark } from './_shared.ts';

export function factorCard(data: {
  id: string;
  name: string;
  description?: string;
  isCritical: boolean;
  categoryName?: string;
  hacksCount?: number;
  protocolsCount?: number;
}): SatoriNode {
  return h('div', {
    style: {
      ...CARD.outer,
      background: data.isCritical ? COLORS.criticalBg : COLORS.bg,
      flexDirection: 'column',
      justifyContent: 'space-between',
    },
  } as never,
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
      logoMark(),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 16, marginBottom: 4 } },
        h('div', {
          style: {
            fontFamily: 'monospace',
            fontSize: 20,
            color: data.isCritical ? COLORS.critical : COLORS.muted,
            background: data.isCritical ? COLORS.criticalBg : COLORS.white,
            padding: '4px 12px',
            borderRadius: 6,
            border: `1px solid ${data.isCritical ? COLORS.critical : COLORS.border}`,
          },
        }, data.id),
        data.isCritical
          ? h('div', {
            style: {
              fontSize: 20,
              fontWeight: 700,
              color: COLORS.critical,
              background: COLORS.criticalBg,
              padding: '4px 14px',
              borderRadius: 999,
            },
          }, '★ critical')
          : null,
        data.categoryName
          ? h('div', {
            style: { fontSize: 16, color: COLORS.muted },
          }, data.categoryName)
          : null,
      ),
      h('div', {
        style: {
          fontSize: 44,
          fontWeight: 700,
          color: COLORS.ink,
          lineHeight: 1.15,
          maxWidth: 920,
        },
      }, data.name),
      data.description
        ? h('div', {
          style: { fontSize: 22, color: COLORS.muted, maxWidth: 860, lineHeight: 1.4 },
        }, data.description.slice(0, 160) + (data.description.length > 160 ? '…' : ''))
        : null,
    ),
    h('div', {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 32,
        paddingTop: 20,
        borderTop: `2px solid ${data.isCritical ? COLORS.gradeF : COLORS.border}`,
      },
    },
      h('div', { style: { fontSize: 16, color: COLORS.muted } }, `defirisk.co/factors/${data.id}/`),
      h('div', { style: { flex: 1 } }),
      data.hacksCount != null
        ? h('div', {
          style: { fontSize: 18, color: COLORS.muted },
        }, `${data.hacksCount} hacks linked`)
        : null,
      data.protocolsCount != null
        ? h('div', {
          style: { fontSize: 18, color: COLORS.muted },
        }, `${data.protocolsCount} protocols`)
        : null,
    ),
  );
}
