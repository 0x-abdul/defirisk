import { h, type SatoriNode } from '../render.ts';
import { COLORS, CARD, logoMark, gradePill } from './_shared.ts';

export function gradeChangeCard(data: {
  protocolName: string;
  protocolSlug: string;
  fromGrade: string;
  toGrade: string;
  detectedAt: string;
  reason?: string;
}): SatoriNode {
  const isUpgrade = ['A', 'B', 'C', 'D', 'F'].indexOf(data.toGrade) <
    ['A', 'B', 'C', 'D', 'F'].indexOf(data.fromGrade);

  return h('div', {
    style: {
      ...CARD.outer,
      background: COLORS.bg,
      flexDirection: 'column',
      justifyContent: 'space-between',
    },
  } as never,
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
      logoMark(),
      h('div', {
        style: {
          fontSize: 20,
          color: isUpgrade ? COLORS.gradeA : COLORS.gradeF,
          fontWeight: 700,
          letterSpacing: '0.05em',
        },
      }, isUpgrade ? '↑ GRADE UPGRADE' : '↓ GRADE DOWNGRADE'),
      h('div', {
        style: {
          fontSize: 46,
          fontWeight: 700,
          color: COLORS.ink,
          lineHeight: 1.1,
        },
      }, data.protocolName),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 20 } },
        gradePill(data.fromGrade, 88),
        h('div', {
          style: { fontSize: 40, color: COLORS.muted, fontWeight: 700 },
        }, '→'),
        gradePill(data.toGrade, 88),
        h('div', { style: { marginLeft: 16 } },
          h('div', {
            style: { fontSize: 18, color: COLORS.muted },
          }, data.detectedAt.slice(0, 10)),
        ),
      ),
      data.reason
        ? h('div', {
          style: { fontSize: 22, color: COLORS.muted, maxWidth: 860, lineHeight: 1.4 },
        }, data.reason.slice(0, 140) + (data.reason.length > 140 ? '…' : ''))
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
      h('div', { style: { fontSize: 16, color: COLORS.muted } }, `defirisk.co/protocols/${data.protocolSlug}/`),
      h('div', { style: { flex: 1 } }),
      h('div', { style: { fontSize: 16, color: COLORS.muted } }, 'DeFi Risk · Grade Changes'),
    ),
  );
}
